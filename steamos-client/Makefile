# ==============================================================================
# DeckDisplay - Makefile for SteamOS (Steam Deck)
# Builds high-performance C binaries optimized for AMD Zen 2 (Van Gogh APU)
# ==============================================================================

CC ?= gcc
CFLAGS ?= -O3 -march=znver2 -mtune=znver2 -Wall -Wextra -pthread
CLIENT_LIBS ?= $(shell pkg-config --cflags --libs sdl2 libavcodec libavformat libavutil)

TARGETS = deckdisplay_touch deckdisplay_client

all: $(TARGETS)

deckdisplay_touch: deckdisplay_touch.c
	$(CC) $(CFLAGS) -o deckdisplay_touch deckdisplay_touch.c

deckdisplay_client: deckdisplay_client.c
	$(CC) $(CFLAGS) -o deckdisplay_client deckdisplay_client.c $(CLIENT_LIBS)

clean:
	rm -f $(TARGETS) *.o

.PHONY: all clean
