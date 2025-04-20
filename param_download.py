#!/usr/bin/env python3

"""
Script to download all parameters from an ArduPilot vehicle using Pymavlink,
save them to a .param file, and upload the file to a GitHub repository.
"""

import time
import os
import subprocess # To run Git commands
from datetime import datetime
# Import the mavutil module from Pymavlink
from pymavlink import mavutil

# --- Configuration ---

# --- Pymavlink Connection ---
# Define the connection string to your ArduPilot device.
# Examples: '/dev/ttyACM0', 'COM3:115200', 'udp:127.0.0.1:14550', 'tcp:127.0.0.1:5760'
connection_string = 'tcp:127.0.0.1:5762' # Example for SITL/UDP
# connection_string = 'COM5:115200' # Example for Windows Serial

# --- GitHub Configuration ---
# !! IMPORTANT !!
# Ensure Git is installed and configured to push to this repository.
# Using SSH keys is highly recommended for security and automation.
# If using HTTPS, you might need a Personal Access Token (PAT) configured.
# Get the FULL path to the local clone of your GitHub repository
# Example Linux: '/home/user/my_ardupilot_params_repo'
# Example Windows: 'C:/Users/user/Documents/GitHub/my_ardupilot_params_repo'
local_repo_path = '.' # <<< CHANGE THIS

# The branch you want to push the parameters to (e.g., 'main', 'master')
github_branch = 'main' # <<< CHANGE THIS if needed

# Optional: Specify a subdirectory within the repo to save the file
# Leave empty '' to save in the root of the repo
repo_subdirectory = 'parameter_backups' # Example: 'parameter_backups'

# --- Helper Functions ---

def run_git_command(command, cwd):
    """Runs a Git command using subprocess and checks for errors."""
    print(f"Running command: {' '.join(command)} in {cwd}")
    try:
        # Execute the command
        # - cwd: Sets the current working directory for the command (essential for Git)
        # - check=True: Raises CalledProcessError if the command returns a non-zero exit code
        # - capture_output=True: Captures stdout and stderr
        # - text=True: Decodes stdout/stderr as text
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True
        )
        print(f"Command successful:\n{result.stdout}")
        return True
    except FileNotFoundError:
        print(f"Error: Git command not found. Is Git installed and in your PATH?")
        return False
    except subprocess.CalledProcessError as e:
        # Print detailed error information if the command fails
        print(f"Error executing command: {' '.join(command)}")
        print(f"Return code: {e.returncode}")
        print(f"Output (stdout):\n{e.stdout}")
        print(f"Output (stderr):\n{e.stderr}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

# --- Main Script ---

def main():
    """Main execution function."""

    # --- 1. Connect and Download Parameters ---
    print(f"Connecting to vehicle on: {connection_string}")
    master = None # Initialize master connection object
    try:
        master = mavutil.mavlink_connection(connection_string, autoreconnect=True)

        print("Waiting for heartbeat...")
        master.wait_heartbeat()
        print(f"Heartbeat received! (System: {master.target_system}, Component: {master.target_component})")

        print("Requesting all parameters...")
        master.mav.param_request_list_send(
            master.target_system,
            master.target_component
        )

        parameters = {}
        param_count_expected = None
        start_time = time.time()
        timeout_seconds = 45 # Increased timeout slightly for potentially slower links

        print(f"Waiting for parameters (timeout: {timeout_seconds} seconds)...")
        while True:
            current_time = time.time()
            if current_time - start_time > timeout_seconds:
                print("\nError: Timeout waiting for parameters.")
                return # Exit the main function on timeout

            msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)

            if msg:
                try:
                    param_id = msg.param_id.decode('ascii').rstrip('\x00')
                except UnicodeDecodeError:
                    print(f"Warning: Could not decode param_id: {msg.param_id}")
                    param_id = None

                if param_id:
                    parameters[param_id] = msg.param_value
                    param_count_expected = msg.param_count
                    param_index_received = msg.param_index

                    print(f"\rReceived {len(parameters)}/{param_count_expected}: {param_id} = {msg.param_value:.6f} (Index: {param_index_received})", end="")

                    start_time = time.time() # Reset timeout timer on successful receive

                    if len(parameters) >= param_count_expected:
                        print("\nSuccessfully received all parameters.")
                        break
            # else: No message received in this 1s interval, loop continues

    except Exception as e:
        print(f"\nError during MAVLink communication: {e}")
        return # Exit if connection or download fails
    finally:
        # Ensure the connection is closed regardless of success or failure
        if master:
            print("Closing MAVLink connection.")
            master.close()

    if not parameters:
        print("No parameters were downloaded. Exiting.")
        return

    print(f"\nTotal parameters downloaded: {len(parameters)}")

    # --- 2. Save Parameters to .param File ---
    # Create a timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    param_filename = f"ardupilot_params_{timestamp}.param"

    # Determine the full path for saving the file (inside the local repo)
    save_directory = local_repo_path
    if repo_subdirectory:
        # If a subdirectory is specified, join it to the repo path
        save_directory = os.path.join(local_repo_path, repo_subdirectory)
        # Create the subdirectory if it doesn't exist
        try:
            os.makedirs(save_directory, exist_ok=True)
            print(f"Ensured directory exists: {save_directory}")
        except OSError as e:
            print(f"Error creating directory {save_directory}: {e}")
            return # Exit if directory creation fails

    full_param_filepath = os.path.join(save_directory, param_filename)

    print(f"Saving parameters to: {full_param_filepath}")
    try:
        with open(full_param_filepath, 'w') as f:
            # Write a standard header
            f.write(f"# ArduPilot Parameter File\n")
            f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            # Try to get vehicle info if connection was successful
            if master and master.target_system != 0:
                 f.write(f"# Vehicle: System={master.target_system}, Component={master.target_component}\n")
            f.write(f"# Parameters: {len(parameters)}\n")
            f.write("#\n") # Blank line separator

            # Write parameters sorted alphabetically
            # Format: PARAM_NAME<tab>VALUE (or PARAM_NAME,VALUE)
            # Using comma separation is very common and readable
            for name, value in sorted(parameters.items()):
                # Format float values for consistency
                if isinstance(value, float):
                    # Use a reasonable number of decimal places, avoid scientific notation for typical params
                    f.write(f"{name},{value:.8f}\n")
                else:
                    f.write(f"{name},{value}\n") # Should ideally always be float from PARAM_VALUE

        print("Parameters saved successfully.")
    except IOError as e:
        print(f"Error saving parameters to file {full_param_filepath}: {e}")
        return # Exit if saving fails

    # --- 3. Upload to GitHub using Git commands ---
    print("\nAttempting to upload parameter file to GitHub...")

    # Check if the local repo path exists
    if not os.path.isdir(local_repo_path):
        print(f"Error: Local repository path not found: {local_repo_path}")
        print("Please ensure the 'local_repo_path' variable is set correctly.")
        return

    # Define the relative path of the file within the repository
    relative_param_filepath = os.path.join(repo_subdirectory, param_filename) if repo_subdirectory else param_filename
    # Ensure using forward slashes for git add, even on Windows
    relative_param_filepath_git = relative_param_filepath.replace(os.path.sep, '/')


    # Git command sequence
    print("--- Git Operations ---")

    # 1. Pull latest changes from remote to avoid conflicts
    if not run_git_command(['git', 'pull', 'origin', github_branch], cwd=local_repo_path):
        print("Git pull failed. Please resolve any conflicts manually and try again.")
        print("Parameter file was saved locally but not uploaded.")
        return

    # 2. Add the new parameter file
    if not run_git_command(['git', 'add', relative_param_filepath_git], cwd=local_repo_path):
        print("Git add failed. Parameter file not staged for commit.")
        return

    # 3. Commit the changes
    commit_message = f"Add ArduPilot parameters backup {timestamp}"
    if not run_git_command(['git', 'commit', '-m', commit_message], cwd=local_repo_path):
        # It's possible 'git commit' fails if there's nothing to commit (e.g., file identical)
        # Check stderr for "nothing to commit" message if needed, but often can proceed.
        print("Git commit failed or nothing to commit.")
        # Decide if you want to stop here or try pushing anyway
        # For simplicity, we'll try pushing. A more robust script would check commit output.
        # return # Uncomment this line to stop if commit fails

    # 4. Push the commit to the remote repository
    if not run_git_command(['git', 'push', 'origin', github_branch], cwd=local_repo_path):
        print("Git push failed. Check your connection, permissions, and Git configuration (SSH/HTTPS).")
        print("Parameter file was saved locally and possibly committed, but not uploaded.")
        return

    print("--- Git Operations Finished ---")
    print(f"Successfully uploaded {param_filename} to GitHub repository branch '{github_branch}'.")
    print("Script finished.")


# --- Run the main function ---
if __name__ == "__main__":
    # Basic check for placeholder path
    if '/path/to/your/local/github/repo' in local_repo_path:
         print("ERROR: Please update the 'local_repo_path' variable in the script!")
    else:
        main()
