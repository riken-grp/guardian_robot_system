#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pulse/pulseaudio.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <netinet/tcp.h>

#define RATE         16000
#define CHANNELS     1
#define SAMPLE_SIZE  2    // 16-bit PCM = 2 bytes
#define CHUNK_SIZE   320  // 10ms at 16kHz mono

static pa_mainloop *mainloop;
static pa_context *context;
static pa_stream *stream;
static int sockfd;

void stream_read_callback(pa_stream *s, size_t length, void *userdata) {
    const void *data;
    if (pa_stream_peek(s, &data, &length) < 0) {
        fprintf(stderr, "pa_stream_peek failed\n");
        return;
    }

    if (data && length > 0) {
        ssize_t total_sent = 0;
        while (total_sent < length) {
            ssize_t sent = send(sockfd, (uint8_t*)data + total_sent, length - total_sent, 0);
            if (sent <= 0) {
                perror("send() failed");
                pa_mainloop_quit(mainloop, 1);
                return;
            }
            total_sent += sent;
        }
    }

    pa_stream_drop(s);
}

void stream_state_callback(pa_stream *s, void *userdata) {
    pa_stream_state_t state = pa_stream_get_state(s);
    if (state == PA_STREAM_FAILED || state == PA_STREAM_TERMINATED) {
        fprintf(stderr, "Stream error: %s\n", pa_strerror(pa_context_errno(context)));
        pa_mainloop_quit(mainloop, 1);
    }
}

void context_state_callback(pa_context *c, void *userdata) {
    if (pa_context_get_state(c) == PA_CONTEXT_READY) {
        pa_sample_spec ss = {
            .format = PA_SAMPLE_S16LE,
            .rate = RATE,
            .channels = CHANNELS
        };

        pa_buffer_attr buffer_attr = {
	  .maxlength =  CHUNK_SIZE, // (uint32_t)-1,
            .fragsize = CHUNK_SIZE
        };

        const char *source_name = userdata;

        stream = pa_stream_new(c, "Audio Stream", &ss, NULL);
        pa_stream_set_state_callback(stream, stream_state_callback, NULL);
        pa_stream_set_read_callback(stream, stream_read_callback, NULL);

	pa_stream_flags_t flags = PA_STREAM_ADJUST_LATENCY | PA_STREAM_INTERPOLATE_TIMING | PA_STREAM_AUTO_TIMING_UPDATE;

        pa_stream_connect_record(stream, source_name, &buffer_attr, flags);
    } else if (pa_context_get_state(c) == PA_CONTEXT_FAILED || pa_context_get_state(c) == PA_CONTEXT_TERMINATED) {
        fprintf(stderr, "Context failed: %s\n", pa_strerror(pa_context_errno(c)));
        pa_mainloop_quit(mainloop, 1);
    }
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <bind_ip> <port> [source]\n", argv[0]);
        return EXIT_FAILURE;
    }

    const char *bind_ip = argv[1];
    int listen_port = atoi(argv[2]);
    const char *source_name = (argc > 3) ? argv[3] : NULL;

    // Setup TCP connection
    int listenfd = -1;
    struct sockaddr_in addr;
    listenfd = socket(AF_INET, SOCK_STREAM, 0);
    if (listenfd < 0) {
        perror("Socket creation failed");
        return EXIT_FAILURE;
    }

    int opt = 1;
    if (setsockopt(listenfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt)) < 0) {
        perror("setsockopt(SO_REUSEADDR) failed");
        close(listenfd);
        return EXIT_FAILURE;
    }    

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)listen_port);
    if (inet_pton(AF_INET, bind_ip, &addr.sin_addr) <= 0) {
        perror("Invalid bind_ip");
        close(listenfd);
        return EXIT_FAILURE;
    }

    if (bind(listenfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind() failed");
        close(listenfd);
        return EXIT_FAILURE;
    }

    if (listen(listenfd, 1) < 0) {
        perror("listen() failed");
        close(listenfd);
        return EXIT_FAILURE;
    }    

    printf("Listening on %s:%d ...\n", bind_ip, listen_port);

    // Accept a single client
    struct sockaddr_in client_addr;
    socklen_t client_len = sizeof(client_addr);
    sockfd = accept(listenfd, (struct sockaddr *)&client_addr, &client_len);
    if (sockfd < 0) {
        perror("accept() failed");
        close(listenfd);
        return EXIT_FAILURE;
    }

    char client_ip[INET_ADDRSTRLEN] = {0};
    inet_ntop(AF_INET, &client_addr.sin_addr, client_ip, sizeof(client_ip));
    printf("Client connected from %s:%d\n", client_ip, ntohs(client_addr.sin_port));

    // single-client restart-only operation!
    close(listenfd);
    
    
    int flag = 1;
    setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(int));

    mainloop = pa_mainloop_new();
    context = pa_context_new(pa_mainloop_get_api(mainloop), "Async Audio Streamer (Server)");
    pa_context_set_state_callback(context, context_state_callback, (void*)source_name);

    if (pa_context_connect(context, NULL, PA_CONTEXT_NOFLAGS, NULL) < 0) {
        fprintf(stderr, "pa_context_connect failed: %s\n", pa_strerror(pa_context_errno(context)));
        if (context) pa_context_unref(context);
        if (mainloop) pa_mainloop_free(mainloop);
        close(sockfd);
        return EXIT_FAILURE;
    }    

    printf("Streaming audio from source %s\n", source_name ? source_name : "default");

    int ret = 0;
    pa_mainloop_run(mainloop, &ret);

    // Cleanup
    if (stream) pa_stream_unref(stream);
    if (context) pa_context_unref(context);
    if (mainloop) pa_mainloop_free(mainloop);
    close(sockfd);

    return ret;
}
