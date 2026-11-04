#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pulse/simple.h>
#include <pulse/error.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <netinet/tcp.h>

#define RATE        16000
#define CHANNELS    1
#define SAMPLE_SIZE 2  // 16-bit PCM = 2 bytes
#define SAMPLE_LENGTH 10 // in ms
#define CHUNK_SIZE 320

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <remote_host> <port> <<OPTIONAL: monitor source>>\n", argv[0]);
        return EXIT_FAILURE;
    }

    const char *server_host = argv[1];
    int server_port = atoi(argv[2]);

    // Setup PulseAudio simple API attributes
    pa_simple *pa_stream = NULL;
    pa_sample_spec ss;
    ss.format = PA_SAMPLE_S16LE;
    ss.rate = RATE;
    ss.channels = CHANNELS;

    int error;

    // Set source to arg3 or default sink monitor
    const char *source_name = (argc > 3 && argv[3][0] != '\0') ? argv[3] : NULL;

    pa_buffer_attr buffer_attr;
    buffer_attr.maxlength = (uint32_t)-1; // default
    buffer_attr.tlength = pa_usec_to_bytes(10000, &ss); // 10ms
    buffer_attr.prebuf = (uint32_t)-1;
    buffer_attr.minreq = (uint32_t)-1;
    buffer_attr.fragsize = (uint32_t)-1;

    pa_stream = pa_simple_new(NULL,               // Default server
                              "C-Audio-Streamer", // App name
                              PA_STREAM_RECORD,   // Record audio
                              source_name,        // Source (sink monitor)
                              "Audio-TCP-Stream", // Stream description
                              &ss,                // Sample format
                              NULL,               // Default channel map
                              &buffer_attr,        // buffer attributes
                              &error);
    if (!pa_stream) {
        fprintf(stderr, "PulseAudio connection failed: %s\n", pa_strerror(error));
        return EXIT_FAILURE;
    }

    // Setup TCP connection
    int sockfd;
    struct sockaddr_in serv_addr;

    printf("Attempting to stream to %s at port %d\n", server_host, server_port);
    if ((sockfd = socket(AF_INET, SOCK_STREAM, 0)) < 0) {
        perror("Socket creation failed");
        pa_simple_free(pa_stream);
        return EXIT_FAILURE;
    }

    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(server_port);

    if (inet_pton(AF_INET, server_host, &serv_addr.sin_addr) <= 0) {
        perror("Invalid address/ Address not supported");
        close(sockfd);
        pa_simple_free(pa_stream);
        return EXIT_FAILURE;
    }

    if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        perror("Connection Failed");
        close(sockfd);
        pa_simple_free(pa_stream);
        return EXIT_FAILURE;
    }

    // Disable Nagle to send immediately
    int send_flag = 1;
    setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &send_flag, sizeof(send_flag));

    // Audio buffer
    uint8_t buffer[CHUNK_SIZE];

    printf("Streaming audio to %s:%d\n", server_host, server_port);

    // Main loop: record and send audio data
    while (1) {
        if (pa_simple_read(pa_stream, buffer, CHUNK_SIZE, &error) < 0) {
            fprintf(stderr, "pa_simple_read() failed: %s\n", pa_strerror(error));
            break;
        }

        ssize_t total_sent = 0;
        while (total_sent < CHUNK_SIZE) {
            ssize_t sent = send(sockfd, buffer + total_sent, CHUNK_SIZE - total_sent, 0);
            if (sent <= 0) {
                perror("send() failed");
                goto cleanup;
            }
            total_sent += sent;
        }
    }

cleanup:
    close(sockfd);
    pa_simple_free(pa_stream);
    return EXIT_SUCCESS;
}
