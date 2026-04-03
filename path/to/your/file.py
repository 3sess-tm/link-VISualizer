def scan_project(path):
    try:
        # Existing logic
        ...
    except ValueError as e:
        # Handle symlink that points outside the root directory
        print(f"Error: {e}")
        return None
