#!/usr/bin/env python3

"""
Script to download all parameters from an ArduPilot vehicle using Pymavlink,
save them to a specified .param file (overwriting previous), and upload the
changes to a GitHub repository.

Accepts command-line arguments for connection string and output filename.
"""

import time
import os
import subprocess # To run Git commands
from datetime import datetime
import argparse # Import the argparse library
# Import the mavutil module from Pymavlink
from pymavlink import mavutil

# --- Configuration (Constants that are less likely to change via CLI) ---

# --- GitHub Configuration ---
# !! RECOMMENDATION !! Use the FULL, ABSOLUTE path to your local repo clone.
# Example Windows: 'C:/Users/dlebe/Documents/Code/ofa-params'
local_repo_path = '.' # <<< STRONGLY RECOMMEND CHANGING to absolute path
# local_repo_path = 'C:/Users/dlebe/Documents/Code/ofa-params' # Example absolute path

github_branch = 'main' # Branch to push to
repo_subdirectory = 'parameter_backups' # Subdirectory within the repo (optional)

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
            encoding='utf-8'
        )
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
        if e.stderr:
            print(f"Output (stderr):\n{e.stderr}")
        if e.stdout:
            print(f"Output (stdout):\n{e.stdout}")
        if "nothing to commit" in e.stderr or "nothing to commit" in e.stdout:
             print("Note: Git reported 'nothing to commit'.")
             return True # Treat as success for commit command
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

# --- Main Script Logic ---

# Modified main to accept parsed arguments object
def main(args):
    """Main execution function, using parsed arguments."""

    # Use connection string and filename from args
    connection_string = args.connection_string
    param_filename = args.param_filename

    # --- 1. Connect and Download Parameters ---
    print(f"Connecting to vehicle on: {connection_string}")
    master = None
    parameters = {}
    param_count_expected = None
    vehicle_info = {"system": "N/A", "component": "N/A"}

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
        if parameters:
            print("Proceeding to save parameters downloaded before the error.")
        else:
            return
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

    # --- 2. Save Parameters to Specified .param File ---
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

    # Use the filename provided via command line argument
    full_param_filepath = os.path.join(save_directory, param_filename)

    print(f"Saving parameters to: {full_param_filepath} (overwriting if exists)")
    try:
        with open(full_param_filepath, 'w', encoding='utf-8') as f:
            f.write(f"# ArduPilot Parameter File\n")
            f.write(f"# Source Connection: {connection_string}\n") # Add connection info
            f.write(f"# Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
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

    # 1. Pull latest changes
    if not run_git_command(['git', 'pull', 'origin', github_branch], cwd=git_cwd):
        print("Git pull failed. Please resolve any conflicts manually and try again.")
        print("Parameter file was saved locally but changes were not committed or pushed.")
        return

    # 2. Add the parameter file
    if not run_git_command(['git', 'add', relative_param_filepath_git], cwd=git_cwd):
        print("Git add failed. Parameter file changes not staged for commit.")
        return

    # 3. Commit the changes
    # Include filename in commit message for clarity when using CLI args
    commit_message = f"Update parameters for {param_filename} ({datetime.now().strftime('%Y-%m-%d')})"
    if not run_git_command(['git', 'commit', '-m', commit_message], cwd=git_cwd):
        # run_git_command handles "nothing to commit"
        print("Git commit failed or nothing to commit.")
        # Decide if we should stop if commit truly failed
        # return # Uncomment to stop if commit fails for reasons other than "nothing to commit"

    # 4. Push the commit
    if not run_git_command(['git', 'push', 'origin', github_branch], cwd=git_cwd):
        print("Git push failed. Check connection, permissions, Git config (SSH/HTTPS), and ensure changes were committed.")
        print("Parameter file was saved locally, possibly committed, but not uploaded.")
        return

    print("--- Git Operations Finished ---")
    print(f"Successfully pushed changes for {param_filename} to GitHub repository branch '{github_branch}'.")
    print("Script finished.")


# --- Script Entry Point ---
if __name__ == "__main__":
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Download ArduPilot parameters, save to a file, and push to GitHub."
    )
    parser.add_argument(
        "-c", "--connection",
        required=True,  # Make connection string mandatory
        dest="connection_string", # Store in args.connection_string
        help="MAVLink connection string (e.g., tcp:127.0.0.1:5760, udp:127.0.0.1:14550, /dev/ttyACM0, COM3:115200)"
    )
    parser.add_argument(
        "-f", "--filename",
        required=False, # Optional
        default="ardupilot_current.param", # Default filename if not provided
        dest="param_filename", # Store in args.param_filename
        help="Output parameter filename (will be overwritten). Default: ardupilot_current.param"
    )
    # Add other arguments here if needed (e.g., --repo-path, --branch)

    args = parser.parse_args() # Parse arguments from command line

    # --- Pre-run Checks ---
    # Check local_repo_path configuration (still relevant even with CLI args)
    if local_repo_path == '.' or '/path/to/your/' in local_repo_path:
         print("---" * 10)
         print("WARNING: 'local_repo_path' is set to '.' or a placeholder.")
         print(f"This script will operate in the current working directory: {os.path.abspath('.')}")
         print("It is STRONGLY recommended to set 'local_repo_path' to the full, absolute path of your local Git repository clone.")
         print("---" * 10)
         confirm = input("Do you want to continue using the current directory? (yes/no): ").lower()
         if confirm != 'yes':
             print("Exiting. Please update 'local_repo_path' in the script or run from the correct directory.")
             exit() # Use exit() instead of return outside a function

    # Check if the resolved repo path exists before calling main
    try:
        absolute_repo_path_check = os.path.abspath(local_repo_path)
        if not os.path.isdir(absolute_repo_path_check):
             print(f"ERROR: The specified 'local_repo_path' does not exist or is not a directory:")
             print(f"  Configured: {local_repo_path}")
             print(f"  Resolved to: {absolute_repo_path_check}")
             print("Please correct the path in the script.")
             exit()
    except Exception as e:
        print(f"Error resolving local_repo_path '{local_repo_path}': {e}")
        exit()

    # --- Execute Main Logic ---
    main(args) # Pass the parsed arguments to the main function
