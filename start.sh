#!/usr/bin/env bash
set -e

echo "================================================"
echo "🚀 Starting ClickLeads Backend on Railway"
echo "================================================"

echo ""
echo "📦 Installing Playwright system dependencies..."
if python -m playwright install-deps; then
    echo "✅ System dependencies installed successfully"
else
    echo "⚠️  Warning: Some system dependencies may have failed"
    echo "    Continuing anyway - Chromium might still work"
fi

echo ""
echo "🌐 Installing Chromium browser..."
if python -m playwright install chromium; then
    echo "✅ Chromium installed successfully"
else
    echo "❌ ERROR: Failed to install Chromium"
    echo "    The application may not work correctly"
    exit 1
fi

echo ""
echo "🔍 Verifying Playwright installation..."
python -c "from playwright.sync_api import sync_playwright; print('✅ Playwright is ready')" || {
    echo "❌ ERROR: Playwright verification failed"
    exit 1
}

echo ""
echo "📋 Environment Configuration:"
echo "   PORT: ${PORT:-8080}"
echo "   HEADLESS: ${HEADLESS:-True}"
echo "   MAX_RETRIES: ${MAX_RETRIES:-5}"
echo "   NAVIGATION_TIMEOUT: ${NAVIGATION_TIMEOUT:-90000}ms"

echo ""
echo "🎯 Starting Uvicorn server..."
echo "================================================"
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --log-level info --access-log
