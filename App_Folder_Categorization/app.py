import os
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import ttkbootstrap as ttkb
import keyring
import openai
from transformers import pipeline
import configparser
import shutil
from urllib.parse import urlparse
import subprocess
import sys
import logging

# Set up logging
logging.basicConfig(filename='organizer.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Define a ToolTip class for adding tooltips to widgets
class ToolTip:
    """A simple tooltip class for Tkinter widgets."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event):
        if self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip_window, text=self.text, background="yellow", 
                         relief="solid", borderwidth=1)
        label.pack()

    def hide_tip(self, event):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class DesktopOrganizer:
    def __init__(self, root):
        """Initialize the Desktop Organizer application."""
        self.root = root
        self.root.title("Desktop Organizer")
        self.files_by_category = {}
        self.full_files_by_category = {}
        self.categories = self.load_categories()
        self.files = []
        self.local_model_name = self.load_model_name()
        self.local_model = None
        self.use_api = False
        self.api_key = keyring.get_password("DesktopOrganizer", "api_key") or ""
        self.api_base = self.load_api_base()
        self.undo_stack = []
        self.lock = threading.Lock()  # Lock for thread safety
        self.current_directory = None  # Track the current directory

        # Check for elevated privileges
        if os.name == "posix" and os.geteuid() == 0:
            messagebox.showwarning("Warning", "Running as root is not recommended.")
        elif os.name == "nt" and ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showwarning("Warning", "Running as administrator is not recommended.")

        self.setup_ui()
        self.load_local_model()

        # Add keyboard shortcuts
        self.root.bind("<Control-b>", lambda event: self.browse_directory())
        self.root.bind("<Control-o>", lambda event: self.organize_files())
        self.root.bind("<Control-z>", lambda event: self.undo_last_organize())
        self.root.bind("<Control-s>", lambda event: self.open_settings())

    def prompt_api_key(self):
        """Prompt user for API key if not found in keyring."""
        api_key = simpledialog.askstring("API Key", "Enter your API key:", parent=self.root)
        if api_key:
            keyring.set_password("DesktopOrganizer", "api_key", api_key)
            logging.info("API key set via prompt.")
            return api_key
        else:
            messagebox.showwarning("Warning", "API key not provided. API features will be disabled.")
            return ""

    def load_categories(self):
        """Load categories from config.ini or return defaults."""
        config = configparser.ConfigParser()
        config.read('config.ini')
        if 'Categories' in config:
            return json.loads(config['Categories'].get('list', '["Documents", "Images", "Music", "Other"]'))
        return ["Documents", "Images", "Music", "Other"]

    def load_model_name(self):
        """Load the selected model name from config.ini or return default."""
        config = configparser.ConfigParser()
        config.read('config.ini')
        if 'Models' in config:
            return config['Models'].get('selected', "facebook/bart-large-mnli")
        return "facebook/bart-large-mnli"

    def load_api_base(self):
        """Load the API base URL from config.ini or return default."""
        config = configparser.ConfigParser()
        config.read('config.ini')
        if 'API' in config:
            return config['API'].get('base_url', "https://api.openai.com/v1")
        return "https://api.openai.com/v1"

    def load_local_model(self):
        """Load the local zero-shot classification model."""
        try:
            self.status_label.config(text="Loading model, please wait...")
            self.root.update_idletasks()
            self.local_model = pipeline("zero-shot-classification", model=self.local_model_name, device='cpu')
            self.status_label.config(text="Model loaded successfully.")
            logging.info(f"Loaded local model: {self.local_model_name}")
        except Exception as e:
            self.status_label.config(text="Failed to load model.")
            messagebox.showerror("Model Error", f"Failed to load model: {str(e)}")
            logging.error(f"Failed to load model {self.local_model_name}: {str(e)}")
            self.local_model = None

    def setup_ui(self):
        """Set up the main user interface."""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)

        # Help button
        help_btn = ttk.Button(main_frame, text="Help", command=self.show_help)
        help_btn.pack(side="top", pady=5)
        ToolTip(help_btn, "View instructions and shortcuts.")

        # Settings button
        settings_btn = ttk.Button(main_frame, text="Settings", command=self.open_settings)
        settings_btn.pack(pady=5)
        ToolTip(settings_btn, "Configure API and model settings.")

        # Directory selection
        ttk.Label(main_frame, text="Directory:").pack(pady=5)
        self.dir_entry = ttk.Entry(main_frame, width=50)
        self.dir_entry.pack(pady=5)
        ToolTip(self.dir_entry, "Path of the directory to organize.")
        browse_btn = ttk.Button(main_frame, text="Browse", command=self.browse_directory)
        browse_btn.pack(pady=5)
        ToolTip(browse_btn, "Select a directory to organize.")

        # Search functionality
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(pady=5)
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.search_entry = ttk.Entry(search_frame)
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", lambda event: self.filter_files(self.search_entry.get()))

        # Progress bar and status label
        self.progress = ttk.Progressbar(main_frame, mode="determinate")
        self.progress.pack(fill="x", pady=5)
        self.status_label = ttk.Label(main_frame, text="Status: Idle")
        self.status_label.pack(pady=5)

        # File Treeview
        self.tree = ttk.Treeview(main_frame, columns=("File", "Local Category", "API Category"), show="tree headings")
        self.tree.heading("File", text="File Name", command=lambda: self.sort_treeview("File", False))
        self.tree.heading("Local Category", text="Local Category", command=lambda: self.sort_treeview("Local Category", False))
        self.tree.heading("API Category", text="API Category", command=lambda: self.sort_treeview("API Category", False))
        self.configure_treeview_columns()  # Set initial column configuration based on self.use_api
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-3>", self.on_treeview_right_click)

        # Organize and undo buttons
        organize_btn = ttk.Button(main_frame, text="Organize", command=self.organize_files)
        organize_btn.pack(side="left", padx=10, pady=10)
        ToolTip(organize_btn, "Move files into category folders.")
        undo_btn = ttk.Button(main_frame, text="Undo Last Organize", command=self.undo_last_organize)
        undo_btn.pack(side="right", padx=10, pady=10)
        ToolTip(undo_btn, "Revert the last organization action.")

    def configure_treeview_columns(self):
        """Configure Treeview columns dynamically based on API status."""
        if self.use_api:
            self.tree.column("API Category", width=150, minwidth=50, stretch=True)
        else:
            self.tree.column("API Category", width=0, minwidth=0, stretch=False)

    def show_help(self):
        """Display a help window with instructions and warnings."""
        help_window = tk.Toplevel(self.root)
        help_window.title("Help")
        help_text = """
        Welcome to Desktop Organizer!

        Instructions:
        1. Click "Browse" to select a directory.
        2. The app will categorize the files.
        3. Click "Organize" to move files into category folders.
        4. Use "Undo Last Organize" to revert the last action.

        Settings:
        - Select API Endpoint: Choose the API for categorization.
        - Select Local Model: Choose the local model for categorization.
        - Use API: Toggle API usage.
        - Manage Categories: Add, remove, or rename categories.

        Keyboard Shortcuts:
        - Ctrl+B: Browse directory
        - Ctrl+O: Organize files
        - Ctrl+Z: Undo last organization
        - Ctrl+S: Open settings

        **WARNING**: Avoid organizing system directories (e.g., C:\\Windows, /etc) to prevent data loss.
        """
        text_widget = tk.Text(help_window, wrap="word", height=20, width=50)
        text_widget.insert("1.0", help_text)
        text_widget.config(state="disabled")
        text_widget.pack(padx=10, pady=10)

    def browse_directory(self):
        """Open a dialog to select a directory and load files."""
        directory = filedialog.askdirectory()
        if directory:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, os.path.realpath(directory))
            self.current_directory = directory
            self.clear_categorizations()
            self.load_files()

    def clear_categorizations(self):
        """Clear existing categorizations and caches for the current directory."""
        self.files_by_category.clear()
        self.full_files_by_category.clear()
        self.tree.delete(*self.tree.get_children())  # Clear Treeview
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "folder_categorization")
        if os.path.exists(cache_dir) and self.current_directory:
            for method in ["local", "api"]:
                cache_file = os.path.join(cache_dir, f"cache_{method}.json")
                if os.path.exists(cache_file):
                    with open(cache_file, "r", encoding='utf-8') as f:
                        cache = json.load(f)
                    # Remove cache entries for the current directory
                    cache = {k: v for k, v in cache.items() if not k.startswith(self.current_directory)}
                    with open(cache_file, "w", encoding='utf-8') as f:
                        json.dump(cache, f)

    def load_files(self):
        """Load files from the selected directory and categorize them."""
        directory = self.dir_entry.get()
        if not os.path.isdir(directory):
            messagebox.showerror("Error", "Invalid directory.")
            return
        self.files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
        self.status_label.config(text="Status: Categorizing files...")
        threading.Thread(target=self.categorize_files, daemon=True).start()

    def categorize_files(self):
        """Categorize files in a background thread."""
        with self.lock:
            self.files_by_category.clear()
        total_files = len(self.files)
        for i, file in enumerate(self.files):
            full_path = os.path.join(self.current_directory, file)
            # Local categorization
            local_category = self.get_cached_prediction(full_path, "local")
            if not local_category and self.local_model:
                local_results = self.predict_local_category([file])
                if local_results and len(local_results) > 0:
                    local_category = local_results[0]["labels"][0]
                else:
                    local_category = "Other"
                self.cache_prediction(full_path, local_category, "local")

            # API categorization
            api_category = "API Disabled"
            if self.use_api and self.api_key:
                api_category = self.get_cached_prediction(full_path, "api")
                if not api_category:
                    api_results = self.predict_api_category([file])
                    if api_results and len(api_results) > 0:
                        api_category = api_results[0]
                    else:
                        api_category = "Other"
                    self.cache_prediction(full_path, api_category, "api")

            # Store the categorized file
            with self.lock:
                if local_category not in self.files_by_category:
                    self.files_by_category[local_category] = {}
                if api_category not in self.files_by_category[local_category]:
                    self.files_by_category[local_category][api_category] = []
                self.files_by_category[local_category][api_category].append(file)

            self.update_progress(i + 1, total_files)
        with self.lock:
            self.full_files_by_category = self.files_by_category.copy()
        self.filter_files("")

    def predict_local_category(self, files):
        """Predict categories using the local model."""
        if not self.local_model:
            return None
        try:
            return self.local_model(files, candidate_labels=self.categories)
        except Exception as e:
            messagebox.showerror("Prediction Error", f"Local prediction failed: {str(e)}")
            logging.error(f"Local prediction failed: {str(e)}")
            return None

    def predict_api_category(self, files):
        """Predict categories using the API with sanitized input."""
        if not self.api_key:
            return ["API Disabled"] * len(files)
        openai.api_key = self.api_key
        openai.api_base = self.api_base
        safe_files = [file.replace(",", "").replace("\n", "") for file in files]  # Sanitize input
        prompt = f"Categorize these files: {', '.join(safe_files)} into {', '.join(self.categories)}"
        try:
            response = openai.Completion.create(
                model="text-davinci-003",
                prompt=prompt,
                max_tokens=100
            )
            categories = response.choices[0].text.strip().split(", ")
            return categories if len(categories) == len(files) else ["Other"] * len(files)
        except openai.error.AuthenticationError:
            messagebox.showerror("API Error", "Authentication failed. Please check your API key.")
            logging.error("API authentication failed.")
            self.api_key = self.prompt_api_key()  # Re-prompt if invalid
            return ["API Error"] * len(files)
        except Exception as e:
            messagebox.showerror("API Error", f"API request failed: {str(e)}")
            logging.error(f"API request failed: {str(e)}")
            return ["API Error"] * len(files)

    def get_cached_prediction(self, file_path, method):
        """Retrieve cached categorization if file hasn’t changed."""
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "folder_categorization")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"cache_{method}.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding='utf-8') as f:
                cache = json.load(f)
            if file_path in cache and cache[file_path]["mtime"] == os.path.getmtime(file_path):
                return cache[file_path]["category"]
        return None

    def cache_prediction(self, file_path, category, method):
        """Cache categorization result with file modification time."""
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "folder_categorization")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"cache_{method}.json")
        cache = {}
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding='utf-8') as f:
                cache = json.load(f)
        cache[file_path] = {"category": category, "mtime": os.path.getmtime(file_path)}
        with open(cache_file, "w", encoding='utf-8') as f:
            json.dump(cache, f)

    def filter_files(self, search_term):
        """Filter files based on the search term and update Treeview."""
        if not search_term:
            with self.lock:
                self.files_by_category = self.full_files_by_category.copy()
        else:
            filtered = {}
            with self.lock:
                for local_cat in self.full_files_by_category:
                    for api_cat in self.full_files_by_category[local_cat]:
                        matching_files = [f for f in self.full_files_by_category[local_cat][api_cat] if search_term.lower() in f.lower()]
                        if matching_files:
                            if local_cat not in filtered:
                                filtered[local_cat] = {}
                            filtered[local_cat][api_cat] = matching_files
                self.files_by_category = filtered
        self.display_files()

    def display_files(self):
        """Display categorized files in the Treeview widget with dynamic configuration."""
        # Configure columns based on API status
        self.configure_treeview_columns()

        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Populate Treeview
        for local_category in self.files_by_category:
            for api_category in self.files_by_category[local_category]:
                # Set parent node text based on API status
                if self.use_api:
                    parent_text = f"{local_category} vs {api_category}"
                else:
                    parent_text = local_category
                parent = self.tree.insert("", "end", text=parent_text)
                for file in self.files_by_category[local_category][api_category]:
                    # Set values, using empty string for API Category when API is disabled
                    values = (file, local_category, api_category if self.use_api else "")
                    self.tree.insert(parent, "end", values=values)

    def sort_treeview(self, col, reverse):
        """Sort the Treeview by the selected column."""
        parents = self.tree.get_children("")
        for parent in parents:
            children = self.tree.get_children(parent)
            data = [(self.tree.set(child, col), child) for child in children]
            data.sort(reverse=reverse)
            for index, (val, child) in enumerate(data):
                self.tree.move(child, parent, index)
        self.tree.heading(col, command=lambda: self.sort_treeview(col, not reverse))

    def on_treeview_right_click(self, event):
        """Handle right-click on Treeview to show a context menu."""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(label="Open file location", command=lambda: self.open_file_location(item))
            menu.add_command(label="Change Category", command=lambda: self.change_file_category(item))
            menu.tk_popup(event.x_root, event.y_root)

    def open_file_location(self, item):
        """Open the file's directory in the system's file explorer."""
        file_name = self.tree.item(item, "values")[0]
        directory = self.dir_entry.get()
        file_path = os.path.join(directory, file_name)
        if os.path.exists(file_path):
            if os.name == 'nt':  # Windows
                os.startfile(os.path.dirname(file_path))
            elif os.name == 'posix':  # Linux or macOS
                if sys.platform == 'darwin':  # macOS
                    subprocess.run(['open', os.path.dirname(file_path)])
                else:  # Linux
                    subprocess.run(['xdg-open', os.path.dirname(file_path)])
        else:
            messagebox.showerror("Error", "File not found.")

    def ask_category(self, parent, file_name, current_category, categories):
        """Custom dialog to select a new category using a combo box."""
        dialog = tk.Toplevel(parent)
        dialog.title("Change Category")
        dialog.geometry("300x150")
        dialog.transient(parent)  # Set to be on top of the parent window
        dialog.grab_set()  # Make the dialog modal

        # Label showing which file is being modified
        ttk.Label(dialog, text=f"Select new category for {file_name}:").pack(pady=10)

        # Combo box with existing categories, pre-selecting the current one
        combo = ttk.Combobox(dialog, values=categories, state="readonly")
        combo.set(current_category)
        combo.pack(pady=5)

        result = None

        def on_ok():
            nonlocal result
            result = combo.get()  # Get the selected category
            dialog.destroy()

        def on_cancel():
            dialog.destroy()  # Close dialog without saving

        # OK and Cancel buttons
        ok_btn = ttk.Button(dialog, text="OK", command=on_ok)
        ok_btn.pack(side="left", padx=20, pady=20)

        cancel_btn = ttk.Button(dialog, text="Cancel", command=on_cancel)
        cancel_btn.pack(side="right", padx=20, pady=20)

        # Handle window close (X button) as Cancel
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        parent.wait_window(dialog)  # Wait for dialog to close
        return result

    def change_file_category(self, item):
        """Allow user to change the category of a selected file using a combo box."""
        file_name = self.tree.item(item, "values")[0]
        current_category = self.tree.item(item, "values")[1]  # Assuming local category is in column 1
        new_category = self.ask_category(self.root, file_name, current_category, self.categories)
        if new_category:
            # Update the categorization in the data structure
            for local_cat in list(self.files_by_category.keys()):
                for api_cat in list(self.files_by_category[local_cat].keys()):
                    if file_name in self.files_by_category[local_cat][api_cat]:
                        self.files_by_category[local_cat][api_cat].remove(file_name)
                        if not self.files_by_category[local_cat][api_cat]:
                            del self.files_by_category[local_cat][api_cat]
                        if not self.files_by_category[local_cat]:
                            del self.files_by_category[local_cat]
                        break
            if new_category not in self.files_by_category:
                self.files_by_category[new_category] = {}
            if "Manual" not in self.files_by_category[new_category]:
                self.files_by_category[new_category]["Manual"] = []
            self.files_by_category[new_category]["Manual"].append(file_name)
            
            # Update the cache
            full_path = os.path.join(self.current_directory, file_name)
            self.cache_prediction(full_path, new_category, "local")
            
            # Refresh the Treeview and full_files_by_category
            self.full_files_by_category = self.files_by_category.copy()
            self.display_files()

    def organize_files(self):
        """Organize files into category folders with undo support and track created folders."""
        directory = self.dir_entry.get()
        if not os.path.isdir(directory):
            messagebox.showerror("Error", "Invalid directory.")
            return
        if not messagebox.askyesno("Confirm", f"Are you sure you want to organize files in {directory}?"):
            return
        move_records = []
        created_folders = set()  # Track folders created during organization
        for local_category in self.files_by_category:
            for api_category in self.files_by_category[local_category]:
                chosen_category = api_category if self.use_api and "API Error" not in api_category else local_category
                category_dir = os.path.join(directory, chosen_category)
                if not os.access(directory, os.W_OK):
                    messagebox.showerror("Error", f"No write access to {directory}")
                    return
                os.makedirs(category_dir, exist_ok=True)
                created_folders.add(category_dir)  # Add to set of created folders
                for file in self.files_by_category[local_category][api_category]:
                    src = os.path.join(directory, file)
                    dest = os.path.join(category_dir, file)
                    try:
                        shutil.move(src, dest)
                        move_records.append((src, dest))
                        logging.info(f"Moved {src} to {dest}")
                    except PermissionError:
                        messagebox.showerror("Error", f"Permission denied to move '{file}'.")
                        logging.error(f"Permission denied moving {file}")
                    except FileNotFoundError:
                        messagebox.showerror("Error", f"File '{file}' not found.")
                        logging.error(f"File not found: {file}")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to move '{file}': {str(e)}")
                        logging.error(f"Failed to move {file}: {str(e)}")
        if move_records:
            self.undo_stack.append((move_records, created_folders))  # Store both move records and created folders
            messagebox.showinfo("Success", "Files organized successfully!")
            self.load_files()

    def undo_last_organize(self):
        """Revert the last file organization and remove empty folders."""
        if not self.undo_stack:
            messagebox.showinfo("Info", "No actions to undo.")
            return
        last_moves, created_folders = self.undo_stack.pop()
        for src, dest in reversed(last_moves):
            try:
                shutil.move(dest, src)
                logging.info(f"Undid move from {dest} to {src}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to undo move for '{dest}': {str(e)}")
                logging.error(f"Undo failed for {dest}: {str(e)}")
        # Remove empty folders
        for folder in created_folders:
            try:
                if os.path.isdir(folder) and not os.listdir(folder):  # Check if folder is empty
                    os.rmdir(folder)
                    logging.info(f"Removed empty folder: {folder}")
            except Exception as e:
                logging.error(f"Failed to remove folder {folder}: {str(e)}")
        messagebox.showinfo("Success", "Undo operation completed.")
        self.load_files()

    def update_progress(self, current, total):
        """Update progress bar and status label."""
        self.progress["value"] = (current / total) * 100
        self.status_label.config(text=f"Status: Processing {current}/{total} files...")
        self.root.update_idletasks()

    def open_settings(self):
        """Open a settings window for customization."""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("400x300")

        # Store previous settings for comparison
        self.prev_categories = self.categories.copy()
        self.prev_model = self.local_model_name
        self.prev_use_api = self.use_api
        self.prev_api_base = self.api_base

        # API Endpoint selection
        ttk.Label(settings_window, text="Select API Endpoint:").pack(pady=5)
        self.api_base_combobox = ttk.Combobox(settings_window, values=[
            "https://api.openai.com/v1",
            "https://api.anthropic.com/v1",
            "https://generativelanguage.googleapis.com/v1",
            "Custom..."
        ])
        self.api_base_combobox.set(self.api_base)
        self.api_base_combobox.pack(pady=5)
        ToolTip(self.api_base_combobox, "Select the API endpoint to use for categorization.")

        # Custom API base entry
        self.custom_api_entry = ttk.Entry(settings_window)
        self.custom_api_entry.pack(pady=5)
        self.custom_api_entry.config(state='disabled')
        ToolTip(self.custom_api_entry, "Enter a custom API base URL.")

        def on_api_base_select(event):
            if self.api_base_combobox.get() == "Custom...":
                self.custom_api_entry.config(state='normal')
            else:
                self.custom_api_entry.config(state='disabled')
        self.api_base_combobox.bind("<<ComboboxSelected>>", on_api_base_select)

        # Local Model selection
        ttk.Label(settings_window, text="Select Local Model:").pack(pady=5)
        self.model_combobox = ttk.Combobox(settings_window, values=["facebook/bart-large-mnli", "distilbert-base-uncased", "roberta-base"])
        self.model_combobox.set(self.local_model_name)
        self.model_combobox.pack(pady=5)
        ToolTip(self.model_combobox, "Select the local model for categorization.")

        # API toggle
        self.api_checkbox = ttk.Checkbutton(settings_window, text="Use API", command=self.toggle_api)
        if self.use_api:
            self.api_checkbox.state(['selected'])
        self.api_checkbox.pack(pady=5)
        ToolTip(self.api_checkbox, "Enable or disable API usage.")

        # Manage Categories button
        manage_categories_btn = ttk.Button(settings_window, text="Manage Categories", command=self.manage_categories)
        manage_categories_btn.pack(pady=5)
        ToolTip(manage_categories_btn, "Add, remove, or rename categories.")

        # Save button
        save_btn = ttk.Button(settings_window, text="Save", command=lambda: self.save_settings(settings_window))
        save_btn.pack(pady=10)
        ToolTip(save_btn, "Save settings and close the window.")

    def toggle_api(self):
        """Toggle API usage."""
        self.use_api = not self.use_api

    def manage_categories(self):
        """Open a window to manage categories."""
        categories_window = tk.Toplevel(self.root)
        categories_window.title("Manage Categories")
        categories_window.geometry("300x400")

        # Listbox to display categories
        listbox = tk.Listbox(categories_window)
        listbox.pack(fill="both", expand=True)

        # Populate listbox with current categories
        for category in self.categories:
            listbox.insert(tk.END, category)

        # Add category
        def add_category():
            new_category = simpledialog.askstring("Add Category", "Enter new category name:", parent=categories_window)
            if new_category and new_category not in self.categories:
                self.categories.append(new_category)
                listbox.insert(tk.END, new_category)
                self.save_categories()

        # Remove category
        def remove_category():
            selected = listbox.curselection()
            if selected:
                category = listbox.get(selected[0])
                if category in self.categories:
                    self.categories.remove(category)
                    listbox.delete(selected[0])
                    self.save_categories()

        # Rename category
        def rename_category():
            selected = listbox.curselection()
            if selected:
                old_category = listbox.get(selected[0])
                new_category = simpledialog.askstring("Rename Category", f"Enter new name for {old_category}:", parent=categories_window)
                if new_category and new_category not in self.categories:
                    index = self.categories.index(old_category)
                    self.categories[index] = new_category
                    listbox.delete(selected[0])
                    listbox.insert(selected[0], new_category)
                    self.save_categories()

        # Buttons for category management
        add_btn = ttk.Button(categories_window, text="Add", command=add_category)
        add_btn.pack(side="left", padx=10, pady=10)
        remove_btn = ttk.Button(categories_window, text="Remove", command=remove_category)
        remove_btn.pack(side="left", padx=10, pady=10)
        rename_btn = ttk.Button(categories_window, text="Rename", command=rename_category)
        rename_btn.pack(side="left", padx=10, pady=10)

    def save_categories(self):
        """Save categories to config.ini."""
        config = configparser.ConfigParser()
        config.read('config.ini')
        if 'Categories' not in config:
            config['Categories'] = {}
        config['Categories']['list'] = json.dumps(self.categories)
        with open('config.ini', 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        logging.info("Categories updated.")

    def save_settings(self, window):
        """Save settings and update configurations."""
        selected_api_base = self.api_base_combobox.get()
        if selected_api_base == "Custom...":
            api_base = self.custom_api_entry.get()
            if not self.is_valid_url(api_base):
                messagebox.showerror("Error", "Invalid custom API base URL. Must be HTTPS.")
                return
        else:
            api_base = selected_api_base
        self.api_base = api_base
        openai.api_base = self.api_base

        new_model = self.model_combobox.get()
        if new_model != self.local_model_name:
            self.local_model_name = new_model
            self.load_local_model()

        # Prompt for API key if API is enabled and no key is set
        if self.use_api and not self.api_key:
            self.api_key = self.prompt_api_key()

        config = configparser.ConfigParser()
        config.read('config.ini')
        if 'API' not in config:
            config['API'] = {}
        config['API']['base_url'] = self.api_base
        if 'Models' not in config:
            config['Models'] = {}
        config['Models']['selected'] = self.local_model_name
        with open('config.ini', 'w', encoding='utf-8') as configfile:
            config.write(configfile)

        # Check if recategorization is needed
        settings_changed = (
            self.categories != self.prev_categories or
            self.local_model_name != self.prev_model or
            self.use_api != self.prev_use_api or
            self.api_base != self.prev_api_base
        )
        window.destroy()
        messagebox.showinfo("Settings", "Settings saved successfully!")
        logging.info("Settings saved.")
        if settings_changed and self.current_directory:
            self.clear_categorizations()
            self.load_files()

    def is_valid_url(self, url):
        """Check if the provided URL is valid and uses HTTPS."""
        try:
            result = urlparse(url)
            return result.scheme == "https" and result.netloc and not result.path.startswith("/")
        except ValueError:
            return False

if __name__ == "__main__":
    import ctypes  # Required for Windows admin check
    root = ttkb.Window(themename="flatly")
    app = DesktopOrganizer(root)
    root.mainloop()
