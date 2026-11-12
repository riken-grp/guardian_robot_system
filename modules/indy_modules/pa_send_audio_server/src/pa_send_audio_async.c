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
        fprintf(stderr, "Usage: %s <remote_host> <port> [source]\n", argv[0]);
        return EXIT_FAILURE;
    }

    const char *server_host = argv[1];
    int server_port = atoi(argv[2]);
    const char *source_name = (argc > 3) ? argv[3] : NULL;

    // Setup TCP connection
    struct sockaddr_in serv_addr;
    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0) {
        perror("Socket creation failed");
        return EXIT_FAILURE;
    }

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(server_port);
    if (inet_pton(AF_INET, server_host, &serv_addr.sin_addr) <= 0) {
        perror("Invalid address");
        close(sockfd);
        return EXIT_FAILURE;
    }

    if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        perror("Connection Failed");
        close(sockfd);
        return EXIT_FAILURE;
    }

    int flag = 1;
    setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(int));

    mainloop = pa_mainloop_new();
    context = pa_context_new(pa_mainloop_get_api(mainloop), "Async Audio Streamer");
    pa_context_set_state_callback(context, context_state_callback, (void*)source_name);
    pa_context_connect(context, NULL, PA_CONTEXT_NOFLAGS, NULL);

    printf("Streaming audio to %s:%d\n", server_host, server_port);

    int ret;
    pa_mainloop_run(mainloop, &ret);

    // Cleanup
    if (stream) pa_stream_unref(stream);
    if (context) pa_context_unref(context);
    if (mainloop) pa_mainloop_free(mainloop);
    close(sockfd);

    return ret;
}
