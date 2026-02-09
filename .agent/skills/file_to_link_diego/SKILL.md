---
name: file_to_link_diego
description: Comprehensive knowledge about the FileToLink-Diego project architecture and functionality.
---

# FileToLink-Diego Project Overview

This project is a high-performance Telegram File to Link bot that allows users to stream and download files directly from Telegram via a web interface.

## 🏗️ Architecture

### 1. Bot Layer (`Thunder/bot/`)
- **`clients.py`**: Manages a pool of Telegram clients (`multi_clients`) for load balancing and avoiding FloodWait.
- **`plugins/`**:
  - `stream.py`: Handles `/link` command and file reception. Generates streaming and download links.
  - `admin.py`: Administrative commands (restart, ban, stats).
  - `callbacks.py`: Handles inline keyboard interactions.
  - `common.py`: Basic commands like `/start`, `/help`, `/about`.

### 2. Server Layer (`Thunder/server/`)
- **`stream_routes.py`**: The heart of the web server (Aiohttp).
  - `/watch/{id}`: Renders the preview page (`req.html`).
  - `/{id}`: Serves the actual file stream.
  - Implements: Range support (for seeking in videos), Load Balancing between bots, and FloodWait fallbacks.

### 3. Core Utilities (`Thunder/utils/`)
- **`custom_dl.py`**: Contains `ByteStreamer`, which handles the low-level asynchronous streaming of files from Telegram's servers.
- **`render_template.py`**: Renders Jinja2 templates (`req.html`, `dl.html`).
- **`database.py`**: Manages data in MongoDB (users, tokens, settings).
- **`vars.py`**: Project configuration and environment variables.

## 🚀 Key Features & Fixes

- **Multi-Client Streaming**: Uses multiple bots to serve content, distributing the load and bypassing single-bot limits.
- **Smart Fallback**: If a bot fails (FloodWait or error), the server automatically switches to another available bot in the middle of the stream.
- **Cinema Experience**: Premium web player (Vidstack) with "Open In" options for external players (VLC, MX Player, etc.).
- **Back to Bot**: Integrated "Back to Bot" button on all web pages to return users to Telegram.
- **Security**: Link hashing and token-based access (optional).
- **Deployment**: Configured for SquareCloud and Heroku.

## 📂 File Map
- `main.py`: Entry point.
- `update.py`: Handles automated updates.
- `config.env`: Environment configuration.
- `squarecloud.app`: SquareCloud deployment config.
- `req.html`: The main streaming template.

## 🛠️ Common Operations
- **Adding new bots**: Add tokens to `config.env` (if supported) or database.
- **Updating UI**: Modify `Thunder/template/req.html`.
- **Debugging Stream**: Check `Thunder/server/stream_routes.py` and `Thunder/utils/custom_dl.py`.
