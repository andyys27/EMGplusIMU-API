# Contributing Guidelines

Thank you for considering contributing to **EMGplusIMU-API**. The following steps will help you set up a development environment and submit improvements.

## Getting Started
1. Fork the repository on GitHub and clone your fork:
   ```bash
   git clone https://github.com/<your-user>/EMGplusIMU-API.git
   cd EMGplusIMU-API
   ```
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install pandas numpy pyserial websocket-client pythonnet PyQt5 pyqtgraph
   ```
3. Ensure that your changes pass basic syntax checks:
   ```bash
   python -m py_compile $(git ls-files "*.py")
   ```

## Code Style
- Follow [PEP8](https://www.python.org/dev/peps/pep-0008/) guidelines.
- Use type hints and descriptive docstrings for all public classes and functions.
- Debug messages should follow the format `[Class] message`.

## Submitting Changes
1. Create a descriptive branch name for your feature or fix.
2. Commit your changes with clear messages and open a pull request against the `main` branch.
3. Describe the motivation for the change and any testing performed.
4. A maintainer will review your PR and may request additional changes.

We appreciate your contributions!
