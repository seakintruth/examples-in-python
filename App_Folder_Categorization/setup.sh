#!/bin/bash
echo "Setting up the environment..."

# Likely Dependancies:
# sudo dnf install rust.x86_64
# sudo dnf install python3.11-tkinter

# Detect the highest Python 3 version available
# PYTHON_CMD=$(ls /usr/bin/python3.* 2>/dev/null | sort -V | tail -n1)
PYTHON_CMD="python3.11"

if [ -z "$PYTHON_CMD" ]; then
    PYTHON_CMD="python3"
fi

# Check if the selected Python command exists
if ! command -v "$PYTHON_CMD" &> /dev/null; then
    echo "Error: No suitable Python 3 version found. Install it with: sudo apt install python3"
    exit 1
fi

echo "Using Python: $PYTHON_CMD"

# Check if the venv module is available for the selected Python
if ! "$PYTHON_CMD" -m venv --help &> /dev/null; then
    echo "Error: The venv module is not available for $PYTHON_CMD. Install it or use a different Python version."
    exit 1
fi

# Define the virtual environment directory
VENV_DIR="venv"

# Create virtual environment if it doesn’t exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment with $PYTHON_CMD..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment. Check your Python installation."
        exit 1
    fi
fi

# Verify the virtual environment was created
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "Error: Virtual environment not created properly. Delete '$VENV_DIR' and try again."
    exit 1
fi

# Activate the virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Check if tkinter is available
if ! "$VENV_DIR/bin/python" -c "import tkinter" &> /dev/null; then
    echo "Error: Tkinter is not installed for this Python version."
    echo "Please install it using your system's package manager."
    echo "For Debian-based systems, run: sudo apt install python3-tk"
    echo "If using a specific Python version (e.g., 3.11), you might need: sudo apt-get install python3.11-tk"
    echo "For fedora systems, run: sudo dnf install python3-tkinter"
    echo "If using a specific Python version (e.g., 3.11), you might need: sudo dnf install python3.11-tkinter"    
    echo "After installing, delete the virtual environment with 'rm -rf $VENV_DIR' and re-run this script."
    deactivate
    exit 1
fi

# Show the Python version in the virtual environment
echo "Virtual environment Python version: $(python --version)"

# Upgrade pip to the latest version
echo "Upgrading pip to the latest version..."
python -m pip install --upgrade pip --quiet
# Run a second upgrade to ensure the latest pip is used
python -m pip install --upgrade pip --quiet

# Check the current pip version
pip_version=$(python -m pip --version)
echo "pip version: $pip_version"

# Install wheel to ensure packages can be built
echo "Installing wheel..."
python -m pip install wheel --quiet

# Install other dependencies
echo "Installing dependencies..."
python -m pip install transformers openai ttkbootstrap keyring pyinstaller --quiet

# Deactivate the virtual environment
deactivate

echo "Setup complete! Activate the environment later with: source $VENV_DIR/bin/activate"
echo "source $VENV_DIR/bin/activate && pip install -r requirements.txt && python3 ./folder_categorization.py"
