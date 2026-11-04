#include <stdio.h>
#include <stdlib.h>
#include <alsa/asoundlib.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <unistd.h>

#define RATE        16000
#define CHANNELS    1
#define FRAMES      160       // 10ms chunks at 16kHz
#define PCM_DEVICE  "hw:Loopback,1,0"  // loopback capture (speaker monitor)

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <remote_host> <port>\n", argv[0]);
        return EXIT_FAILURE;
    }

    const char *server_host = argv[1];
    int server_port = atoi(argv[2]);

    // ALSA setup
    snd_pcm_t *pcm_handle;
    snd_pcm_hw_params_t *params;
    unsigned int rate = RATE;
    int pcm, dir;

    if ((pcm = snd_pcm_open(&pcm_handle, PCM_DEVICE, SND_PCM_STREAM_CAPTURE, 0)) < 0) {
        fprintf(stderr, "Error opening PCM device: %s\n", snd_strerror(pcm));
        return EXIT_FAILURE;
    }

    snd_pcm_hw_params_alloca(&params);
    snd_pcm_hw_params_any(pcm_handle, params);
    snd_pcm_hw_params_set_access(pcm_handle, params, SND_PCM_ACCESS_RW_INTERLEAVED);
    snd_pcm_hw_params_set_format(pcm_handle, params, SND_PCM_FORMAT_S16_LE);
    snd_pcm_hw_params_set_channels(pcm_handle, params, CHANNELS);
    snd_pcm_hw_params_set_rate_near(pcm_handle, params, &rate, &dir);
    snd_pcm_hw_params_set_period_size(pcm_handle, params, FRAMES, dir);

    if ((pcm = snd_pcm_hw_params(pcm_handle, params)) < 0) {
        fprintf(stderr, "Error setting HW params: %s\n", snd_strerror(pcm));
        snd_pcm_close(pcm_handle);
        return EXIT_FAILURE;
    }

    // Network setup
    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in serv_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(server_port)
    };

    if (inet_pton(AF_INET, server_host, &serv_addr.sin_addr) <= 0) {
        perror("Invalid address");
        snd_pcm_close(pcm_handle);
        close(sockfd);
        return EXIT_FAILURE;
    }

    if (connect(sockfd, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        perror("Connection failed");
        snd_pcm_close(pcm_handle);
        close(sockfd);
        return EXIT_FAILURE;
    }

    // Disable Nagle’s algorithm
    int flag = 1;
    setsockopt(sockfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(int));

    int16_t buffer[FRAMES * CHANNELS];

    printf("Streaming speaker output at %uHz...\n", rate);

    // Recording and streaming loop
    while (1) {
        if ((pcm = snd_pcm_readi(pcm_handle, buffer, FRAMES)) == -EPIPE) {
            fprintf(stderr, "XRUN detected, recovering...\n");
            snd_pcm_prepare(pcm_handle);
        } else if (pcm < 0) {
            fprintf(stderr, "PCM read error: %s\n", snd_strerror(pcm));
            break;
        }

        ssize_t sent = send(sockfd, buffer, FRAMES * CHANNELS * sizeof(int16_t), 0);
        if (sent <= 0) {
            perror("send failed");
            break;
        }
    }

    snd_pcm_drain(pcm_handle);
    snd_pcm_close(pcm_handle);
    close(sockfd);

    return EXIT_SUCCESS;
}
