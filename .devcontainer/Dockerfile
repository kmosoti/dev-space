FROM mcr.microsoft.com/devcontainers/base:noble

# Install system dependencies
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    build-essential \
    pkg-config \
    libssl-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# Switch to the non-root user for tooling installation
USER vscode
WORKDIR /home/vscode

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.js | sh -s -- -y
ENV PATH="/home/vscode/.cargo/bin:${PATH}"

# Install uv (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/home/vscode/.cargo/bin:/home/vscode/.local/bin:${PATH}"
