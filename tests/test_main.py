# Unit tests for src/viewscope/main.py

from viewscope.main import main


def test_main():
    """Test the main function."""
    assert main() is None
