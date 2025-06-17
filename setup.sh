#!/bin/bash

# FastAPI Render.com Boilerplate - Local Development Script

set -e

echo "🚀 FastAPI Render.com Boilerplate Setup"
echo "========================================"

# Check if UV is installed
if ! command -v uv &> /dev/null; then
    echo "📦 Installing UV package manager..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install dependencies
echo "📦 Installing dependencies..."
uv sync

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚙️  Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your API keys before running the application"
fi

echo "✅ Setup complete!"
echo ""
echo "🔧 Available commands:"
echo "  uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload  # Start development server"
echo "  uv run pytest                                                     # Run tests"
echo "  uv run black .                                                    # Format code"
echo "  uv run mypy app/                                                  # Type checking"
echo ""
echo "📚 Documentation: http://localhost:8000/docs (after starting server)"
echo "🏥 Health check: http://localhost:8000/health"

