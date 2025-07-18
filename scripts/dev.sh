#!/bin/bash

# Load environment variables
source .env.dev

# Store original directory
ORIGINAL_DIR=$(pwd)

# Function to cleanup processes on script exit
cleanup() {
    echo "Stopping development servers..."
    # Kill any running processes with the specific ports
    pkill -f "fastapi.*--port $BACKEND_PORT" 2>/dev/null
    pkill -f "npm run dev.*--port $FRONTEND_PORT" 2>/dev/null
    exit 0
}

# Set up trap to cleanup on script termination
trap cleanup SIGINT SIGTERM

echo "Starting development servers..."
echo "Backend will run on port $BACKEND_PORT"
echo "Frontend will run on port $FRONTEND_PORT"

# Function to detect available terminal emulator
get_terminal() {
    echo "Checking for available terminal emulators..." >&2
    # Test each terminal for availability
    if command -v xterm &> /dev/null; then
        echo "Found xterm" >&2
        echo "xterm -e"
        return 0
    elif command -v konsole &> /dev/null; then
        echo "Found konsole" >&2
        echo "konsole -e"
        return 0
    elif command -v terminator &> /dev/null; then
        echo "Found terminator" >&2
        echo "terminator -e"
        return 0
    elif command -v mate-terminal &> /dev/null; then
        echo "Found mate-terminal" >&2
        echo "mate-terminal -e"
        return 0
    elif command -v xfce4-terminal &> /dev/null; then
        echo "Found xfce4-terminal" >&2
        echo "xfce4-terminal -e"
        return 0
    elif command -v tilix &> /dev/null; then
        echo "Found tilix" >&2
        echo "tilix -e"
        return 0
    else
        echo "No terminal emulators found" >&2
        return 1
    fi
}

TERMINAL=$(get_terminal)
if [ $? -ne 0 ]; then
    echo "No terminal emulator found. Starting servers in background instead..."
    echo "Logs will be written to backend.log and frontend.log"
    
    # Start backend in background with logging
    cd "$ORIGINAL_DIR/backend" && poetry install && poetry run python3 -m fastapi dev main.py --host $DOMAIN --port $BACKEND_PORT --reload > ../logs/backend.log 2>&1 &
    BACKEND_PID=$!
    
    # Start frontend in background with logging
    cd "$ORIGINAL_DIR/frontend" && npm install && npm run dev -- --port $FRONTEND_PORT > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    
    echo "Backend started (PID: $BACKEND_PID) - logs in backend.log"
    echo "Frontend started (PID: $FRONTEND_PID) - logs in frontend.log"
    echo "Use 'tail -f backend.log' or 'tail -f frontend.log' to view logs"
else
    # Start backend in separate terminal
    $TERMINAL bash -c "cd '$ORIGINAL_DIR/backend' && poetry install && poetry run python3 -m fastapi dev main.py --host $DOMAIN --port $BACKEND_PORT --reload; read -p 'Press Enter to close...'" &

    # Start frontend in separate terminal
    $TERMINAL bash -c "cd '$ORIGINAL_DIR/frontend' && npm install && npm run dev -- --port $FRONTEND_PORT; read -p 'Press Enter to close...'" &
    
    echo "Servers started in separate terminals."
fi

echo "Press Ctrl+C to stop all servers."

# Keep script running until interrupted
while true; do
    sleep 1
done
