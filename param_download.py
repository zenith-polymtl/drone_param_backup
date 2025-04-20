#!/usr/bin/env python3

"""
Script to download all parameters from an ArduPilot vehicle using Pymavlink,
save them to a FIXED .param file (overwriting previous), and upload the
changes to a GitHub repository.
"""

import time
import os
import subprocess # To run Git commands
from datetime import datetime
# Import the mavutil module from Pymavlink
from pymavlink import mavutil

# --- Configuration ---

# --- Pymavlink Connection ---
connection_string = 'tcp:127.0.0.1:5762' # Your setting

# --- GitHub Configuration ---
# !! RECOMMENDATION !! Use the FULL, ABSOLUTE path to your local repo clone.
# Example Windows: 'C:/Users/dlebe/Documents/Code/ofa-params'
local_repo_path = '.' # <<< STRONGLY RECOMMEND CHANGING to absolute path
# local_repo_path = 'C:/Users/dlebe/Documents/Code/ofa-params' # Example absolute path

github_branch = 'main' # Branch to push to
repo_subdirectory = 'parameter_backups' # Subdirectory within the repo (optional)

# --- Fixed Parameter Filename ---
# Use a constant filename instead of a timestamped one
param_filename = "ardupilot_current.param" # <<< Fixed filename

# --- Helper Functions ---

def run_git_command(command, cwd):
    """Runs a Git command using subprocess and checks for errors."""
    print(f"Running command: {' '.join(command)} in {cwd}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8' # Explicitly set encoding
        )
        # Only print stdout if it's not empty, for cleaner logs
        if result.stdout:
            print(f"Command successful:\n{result.stdout}")
        else:
            print("Command successful (no stdout).")
        return True
    except FileNotFoundError:
        print(f"Error: Git command not found. Is Git installed and in your PATH?")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(command)}")
        print(f"Return code: {e.returncode}")
        # Print stderr first as it often contains the core error message
        if e.stderr:
            print(f"Output (stderr):\n{e.stderr}")
        if e.stdout:
            print(f"Output (stdout):\n{e.stdout}")
        # Check specifically for "nothing to commit" which isn't a failure
        if "nothing to commit" in e.stderr or "nothing to commit" in e.stdout:
             print("Note: Git reported 'nothing to commit'.")
             return True # Treat as success for commit command
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

# --- Main Script ---

def main():
    """Main execution function."""

    # --- 1. Connect and Download Parameters ---
    print(f"Connecting to vehicle on: {connection_string}")
    master = None
    parameters = {}
    param_count_expected = None
    vehicle_info = {"system": "N/A", "component": "N/A"} # Store vehicle info

    try:
        master = mavutil.mavlink_connection(connection_string, autoreconnect=True)

        print("Waiting for heartbeat...")
        hb = master.wait_heartbeat(timeout=10)
        if hb is None:
            print("Error: Timed out waiting for heartbeat. Check connection.")
            return
        vehicle_info["system"] = master.target_system
        vehicle_info["component"] = master.target_component
        print(f"Heartbeat received! (System: {vehicle_info['system']}, Component: {vehicle_info['component']})")


        print("Requesting all parameters...")
        master.mav.param_request_list_send(
            master.target_system,
            master.target_component
        )

        start_time = time.time()
        timeout_seconds = 45

        print(f"Waiting for parameters (timeout: {timeout_seconds} seconds)...")
        while True:
            current_time = time.time()
            if current_time - start_time > timeout_seconds:
                print("\nError: Timeout waiting for parameters.")
                if not parameters:
                     print("No parameters received before timeout.")
                else:
                     print(f"Received {len(parameters)} parameters before timeout.")
                return

            msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)

            if msg:
                try:
                    param_id = msg.param_id.rstrip('\x00')
                except AttributeError:
                    print(f"\nWarning: Could not process param_id: {msg.param_id}")
                    param_id = None

                if param_id:
                    if param_count_expected is None:
                        param_count_expected = msg.param_count

                    parameters[param_id] = msg.param_value
                    param_index_received = msg.param_index

                    print(f"\rReceived {len(parameters)}/{param_count_expected}: {param_id} = {msg.param_value} (Index: {param_index_received})", end="")
                    start_time = time.time()

                    if param_count_expected is not None and param_index_received == param_count_expected - 1:
                        parameters[param_id] = msg.param_value
                        print(f"\rReceived {len(parameters)}/{param_count_expected}: {param_id} = {msg.param_value} (Index: {param_index_received})", end="")
                        print("\nSuccessfully received all parameters (based on index).")
                        break
                    elif param_count_expected is not None and len(parameters) >= param_count_expected:
                         print("\nWarning: Parameter download completion based on count, not index.")
                         print("\nSuccessfully received all parameters (based on count).")
                         break

    except Exception as e:
        import traceback
        print(f"\nError during MAVLink communication:")
        traceback.print_exc()
        # Keep any parameters downloaded before the error
        if parameters:
            print("Proceeding to save parameters downloaded before the error.")
        else:
            return # Exit if connection or download fails completely
    finally:
        if master:
            print("Closing MAVLink connection.")
            master.close()

    if not parameters:
        print("No parameters were downloaded. Exiting.")
        return

    print(f"\nTotal parameters downloaded: {len(parameters)}")
    if param_count_expected is not None and len(parameters) != param_count_expected:
        print(f"Warning: Expected {param_count_expected} parameters, but downloaded {len(parameters)}.")

    # --- 2. Save Parameters to Fixed .param File ---
    try:
        absolute_repo_path = os.path.abspath(local_repo_path)
        if not os.path.isdir(absolute_repo_path):
             print(f"Error: Resolved repository path is not a valid directory: {absolute_repo_path}")
             print(f"Check the 'local_repo_path' setting: {local_repo_path}")
             return
    except Exception as e:
        print(f"Error resolving local_repo_path '{local_repo_path}': {e}")
        return

    save_directory = absolute_repo_path
    if repo_subdirectory:
        save_directory = os.path.join(absolute_repo_path, repo_subdirectory)
        try:
            os.makedirs(save_directory, exist_ok=True)
            print(f"Ensured directory exists: {save_directory}")
        except OSError as e:
            print(f"Error creating directory {save_directory}: {e}")
            return

    # Use the fixed filename defined earlier
    full_param_filepath = os.path.join(save_directory, param_filename)

    print(f"Saving parameters to: {full_param_filepath} (overwriting if exists)")
    try:
        with open(full_param_filepath, 'w', encoding='utf-8') as f:
            f.write(f"# ArduPilot Parameter File\n")
            f.write(f"# Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            # Use stored vehicle info
            f.write(f"# Vehicle: System={vehicle_info['system']}, Component={vehicle_info['component']}\n")
            f.write(f"# Parameters: {len(parameters)}\n")
            f.write("#\n")

            for name, value in sorted(parameters.items()):
                if isinstance(value, float):
                    f.write(f"{name},{value:.8f}\n")
                else:
                    f.write(f"{name},{value}\n")

        print("Parameters saved successfully.")
    except IOError as e:
        print(f"Error saving parameters to file {full_param_filepath}: {e}")
        return

    # --- 3. Upload to GitHub using Git commands ---
    print("\nAttempting to commit and push parameter file changes to GitHub...")

    relative_param_filepath = os.path.join(repo_subdirectory, param_filename) if repo_subdirectory else param_filename
    relative_param_filepath_git = relative_param_filepath.replace(os.path.sep, '/')
    git_cwd = absolute_repo_path

    print("--- Git Operations ---")

    # 1. Pull latest changes (important before committing local changes)
    if not run_git_command(['git', 'pull', 'origin', github_branch], cwd=git_cwd):
        print("Git pull failed. Please resolve any conflicts manually and try again.")
        print("Parameter file was saved locally but changes were not committed or pushed.")
        return

    # 2. Add the parameter file (stages changes or adds if new)
    if not run_git_command(['git', 'add', relative_param_filepath_git], cwd=git_cwd):
        print("Git add failed. Parameter file changes not staged for commit.")
        return

    # 3. Commit the changes
    # Use a more generic commit message for updates
    commit_message = f"Update ArduPilot parameters ({datetime.now().strftime('%Y-%m-%d')})"
    # The run_git_command function now handles "nothing to commit" gracefully
    if not run_git_command(['git', 'commit', '-m', commit_message], cwd=git_cwd):
        # If commit truly failed (and wasn't just "nothing to commit")
        print("Git commit failed. Check Git status and logs.")
        # We might still try to push if the only "failure" was "nothing to commit"
        # but let's be cautious and stop if run_git_command returned False here.
        return

    # 4. Push the commit
    if not run_git_command(['git', 'push', 'origin', github_branch], cwd=git_cwd):
        print("Git push failed. Check connection, permissions, Git config (SSH/HTTPS), and ensure changes were committed.")
        print("Parameter file was saved locally, possibly committed, but not uploaded.")
        return

    print("--- Git Operations Finished ---")
    print(f"Successfully pushed changes for {param_filename} to GitHub repository branch '{github_branch}'.")
    print("Script finished.")


# --- Run the main function ---
if __name__ == "__main__":
    if local_repo_path == '.' or '/path/to/your/' in local_repo_path:
         print("---" * 10)
         print("WARNING: 'local_repo_path' is set to '.' or a placeholder.")
         print(f"This script will operate in the current working directory: {os.path.abspath('.')}")
         print("It is STRONGLY recommended to set 'local_repo_path' to the full, absolute path of your local Git repository clone.")
         print("---" * 10)
         confirm = input("Do you want to continue using the current directory? (yes/no): ").lower()
         if confirm == 'yes':
             main()
         else:
             print("Exiting. Please update 'local_repo_path' in the script.")
    else:
        if not os.path.isdir(local_repo_path):
             print(f"ERROR: The specified 'local_repo_path' does not exist or is not a directory: {local_repo_path}")
             print("Please correct the path in the script.")
        else:
            main()
