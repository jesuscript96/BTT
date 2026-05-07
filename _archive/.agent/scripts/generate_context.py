
import os

# Configuration
ROOT_DIR = '/Users/jvch/Desktop/AutomatoWebs/BTT'
OUTPUT_FILE = '/Users/jvch/Desktop/AutomatoWebs/BTT/project_context.md'

# Files/Directories to exclude (names only)
EXCLUDE_DIRS = {
    'node_modules', 'venv', 'data', 'dist', 'build', 'coverage', '__pycache__'
}

EXCLUDE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.pdf', '.zip', '.tar', '.gz', 
    '.pyc', '.pyo', '.exe', '.dll', '.so', '.dylib', '.class', '.jar', '.log', 
    '.DS_Store', '.lock', '.sqlite', '.db', '.sqlite3', '.mp4', '.mov', '.avi'
}

EXCLUDE_FILES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock', 'Cargo.lock',
    '.env', '.env.local', '.env.development', '.env.production', # Security
    'project_context.md', # Exclude self
    'generate_context.py' # Exclude this script
}

def is_text_file(filename):
    """Check if file is likely a text file based on extension."""
    _, ext = os.path.splitext(filename)
    return ext not in EXCLUDE_EXTENSIONS

def generate_context():
    print(f"Generating context file at: {OUTPUT_FILE}")
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
            outfile.write(f"# Project Context\n\nGenerated from {ROOT_DIR}\n\n")
            
            for root, dirs, files in os.walk(ROOT_DIR):
                # Filter directories
                # Exclude dot-directories (e.g. .git, .vscode, .venv) and specific exclude list
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in EXCLUDE_DIRS]
                
                for file in files:
                    if file in EXCLUDE_FILES:
                        continue
                    
                    if not is_text_file(file):
                        continue
                    
                    # Also exclude dot-files if not explicitly allowed (optional, but good for cleanup)
                    if file.startswith('.') and file not in ['.gitignore', '.dockerignore']:
                        continue
                        
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, ROOT_DIR)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as infile:
                            content = infile.read()
                            
                        outfile.write(f"\n\n# File: {relative_path}\n")
                        # Determine language for markdown code block
                        _, ext = os.path.splitext(file)
                        lang = ext.lstrip('.') if ext else ''
                        if lang == 'tsx' or lang == 'ts': lang = 'typescript'
                        if lang == 'jsx' or lang == 'js': lang = 'javascript'
                        if lang == 'py': lang = 'python'
                        
                        outfile.write(f"```{lang}\n")
                        outfile.write(content)
                        outfile.write("\n```\n")
                        print(f"Added: {relative_path}")
                        
                    except UnicodeDecodeError:
                        print(f"Skipping binary/non-utf8 file: {relative_path}")
                    except Exception as e:
                        print(f"Error reading {relative_path}: {e}")
                        
        print("Context generation complete.")
        
    except Exception as e:
        print(f"Failed to create output file: {e}")

if __name__ == "__main__":
    generate_context()
