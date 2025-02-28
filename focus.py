def clear_today_tasks():
    """Delete all tasks for today"""
    log_file = get_day_log_file()
    if log_file.exists():
        # Create a backup first
        backup_file = log_file.with_suffix('.backup')
        import shutil
        shutil.copy2(log_file, backup_file)
        
        # Delete the file
        log_file.unlink()
        
        # Create a new empty file with just the header
        initialize_day_log()
    
    # Make sure statistics get updated
    update_statistics()#!/usr/bin/env python3
"""
Focus Tracker - A simple productivity tool for terminal users
Prompts for the current task and sends reminders at configurable intervals
Logs task history to CSV files organized by month
Supports interactive commands during execution
"""

import time
import os
import sys
import subprocess
import datetime
import json
import signal
import argparse
import csv
import threading
import select
import queue
from pathlib import Path

# Configuration
CONFIG_DIR = Path.home() / ".config" / "focus-tracker"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_CONFIG = {
    "reminder_interval": 30,  # minutes
    "notification_timeout": 10000,  # milliseconds
    "auto_start": False,
    "log_tasks": True
}

# Data directories
DATA_DIR = Path.home() / ".local" / "share" / "focus-tracker"
STATS_FILE = DATA_DIR / "statistics.csv"

def setup():
    """Create config and data directories and files if they don't exist"""
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True)
    
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True)
    
    # Create statistics file if it doesn't exist
    if not STATS_FILE.exists():
        with open(STATS_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", 
                "Tasks Completed", 
                "Completed Time (min)", 
                "Avg Completed Time (min)",
                "Tasks Abandoned",
                "Abandoned Time (min)",
                "Avg Abandoned Time (min)",
                "Completion Rate (%)"
            ])

def load_config():
    """Load configuration from file"""
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_month_dir():
    """Get the directory for the current month's logs"""
    today = datetime.datetime.now()
    month_dir = DATA_DIR / f"{today.year}_{today.month:02d}"
    if not month_dir.exists():
        month_dir.mkdir(parents=True)
    return month_dir

def get_day_log_file():
    """Get the CSV log file for the current day"""
    today = datetime.datetime.now()
    month_dir = get_month_dir()
    return month_dir / f"tasks_{today.year}_{today.month:02d}_{today.day:02d}.csv"

def initialize_day_log():
    """Initialize the daily log file if it doesn't exist"""
    log_file = get_day_log_file()
    if not log_file.exists():
        with open(log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Task", "Start Time", "End Time", "Duration (minutes)", "Status"])

def update_task_status(task_name, new_status):
    """Update the status of a task in today's log"""
    log_file = get_day_log_file()
    if not log_file.exists():
        return False
    
    # Read all rows
    rows = []
    with open(log_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["Task"] == task_name and row["Status"] in ["Abandoned", "In Progress"]:
                row["Status"] = new_status
            rows.append(row)
    
    # Write back all rows
    with open(log_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    return True

def log_task(task, start_time, end_time=None, status="In Progress"):
    """Log task to the daily CSV file"""
    log_file = get_day_log_file()
    
    # Check if the file exists
    file_exists = log_file.exists()
    
    # If updating an abandoned task and resuming it, update the existing entry
    updating_abandoned = False
    if status == "In Progress":
        # Check if this task exists as abandoned in today's log
        if file_exists:
            with open(log_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                # Find abandoned entries for this task name
                for row in rows:
                    if row["Task"] == task and row["Status"] == "Abandoned":
                        updating_abandoned = True
                        break
            
            # If we found an abandoned entry for this task, update it rather than creating a new one
            if updating_abandoned:
                update_task_status(task, "In Progress (Resumed)")
                return
    
    # Calculate duration if end_time is provided
    duration = None
    if end_time:
        duration = (end_time - start_time).total_seconds() / 60  # in minutes
    
    # Convert times to strings
    start_str = start_time.strftime("%H:%M:%S")
    end_str = end_time.strftime("%H:%M:%S") if end_time else ""
    
    with open(log_file, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Task", "Start Time", "End Time", "Duration (minutes)", "Status"])
        
        writer.writerow([
            task,
            start_str,
            end_str,
            f"{duration:.2f}" if duration else "",
            status
        ])

def get_abandoned_tasks():
    """Get a list of abandoned tasks from all logs"""
    abandoned_tasks = []
    
    # Check for tasks in the current month
    month_dir = get_month_dir()
    if not month_dir.exists():
        return abandoned_tasks
    
    # Get all CSV files in the month directory
    csv_files = list(month_dir.glob("*.csv"))
    
    # Get the most recent abandoned tasks
    for csv_file in sorted(csv_files, reverse=True):
        if not csv_file.exists():
            continue
        
        with open(csv_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Status"] == "Abandoned":
                    # Add to list if not already in it (by task name)
                    if not any(t['Task'] == row['Task'] for t in abandoned_tasks):
                        abandoned_tasks.append(row)
        
        # Limit to the 10 most recent abandoned tasks
        if len(abandoned_tasks) >= 10:
            break
    
    return abandoned_tasks[:10]  # Return at most 10 tasks

def update_statistics():
    """Update the statistics CSV with data from today and yesterday"""
    today = datetime.datetime.now().date()
    yesterday = today - datetime.timedelta(days=1)
    
    # Process today and yesterday
    for day in [yesterday, today]:
        month_dir = DATA_DIR / f"{day.year}_{day.month:02d}"
        day_file = month_dir / f"tasks_{day.year}_{day.month:02d}_{day.day:02d}.csv"
        
        if not day_file.exists():
            continue
        
        # Read the day's tasks
        completed_tasks = []
        abandoned_tasks = []
        total_completed_duration = 0
        total_abandoned_duration = 0
        
        with open(day_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Status"] == "Completed" and row["Duration (minutes)"]:
                    completed_tasks.append(row)
                    try:
                        total_completed_duration += float(row["Duration (minutes)"])
                    except ValueError:
                        pass
                elif row["Status"] == "Abandoned" and row["Duration (minutes)"]:
                    abandoned_tasks.append(row)
                    try:
                        total_abandoned_duration += float(row["Duration (minutes)"])
                    except ValueError:
                        pass
        
        # Skip if no tasks
        if not completed_tasks and not abandoned_tasks:
            continue
        
        # Calculate statistics
        day_str = day.strftime("%Y-%m-%d")
        tasks_completed = len(completed_tasks)
        tasks_abandoned = len(abandoned_tasks)
        avg_completed_duration = total_completed_duration / tasks_completed if tasks_completed > 0 else 0
        avg_abandoned_duration = total_abandoned_duration / tasks_abandoned if tasks_abandoned > 0 else 0
        completion_rate = tasks_completed / (tasks_completed + tasks_abandoned) * 100 if (tasks_completed + tasks_abandoned) > 0 else 0
        
        # Check if this day already exists in statistics
        existing_stats = []
        if STATS_FILE.exists():
            with open(STATS_FILE, 'r', newline='') as f:
                reader = csv.reader(f)
                headers = next(reader, None)  # Skip header
                existing_stats = list(reader)
        
        # Update or add the statistics
        day_updated = False
        for i, row in enumerate(existing_stats):
            if row[0] == day_str:
                existing_stats[i] = [
                    day_str, 
                    tasks_completed, 
                    f"{total_completed_duration:.2f}", 
                    f"{avg_completed_duration:.2f}",
                    tasks_abandoned,
                    f"{total_abandoned_duration:.2f}",
                    f"{avg_abandoned_duration:.2f}",
                    f"{completion_rate:.1f}"
                ]
                day_updated = True
                break
        
        if not day_updated:
            existing_stats.append([
                day_str, 
                tasks_completed, 
                f"{total_completed_duration:.2f}", 
                f"{avg_completed_duration:.2f}",
                tasks_abandoned,
                f"{total_abandoned_duration:.2f}",
                f"{avg_abandoned_duration:.2f}",
                f"{completion_rate:.1f}"
            ])
        
        # Write back to statistics file
        with open(STATS_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Date", 
                "Tasks Completed", 
                "Completed Time (min)", 
                "Avg Completed Time (min)",
                "Tasks Abandoned",
                "Abandoned Time (min)",
                "Avg Abandoned Time (min)",
                "Completion Rate (%)"
            ])
            writer.writerows(existing_stats)

def send_notification(title, message):
    """Send a desktop notification"""
    try:
        timeout = load_config()["notification_timeout"]
        subprocess.run([
            "notify-send",
            title,
            message,
            "--urgency=normal",
            f"--expire-time={timeout}"
        ])
        return True
    except Exception as e:
        print(f"Failed to send notification: {e}")
        return False

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        subprocess.run(["notify-send", "--version"], 
                      stdout=subprocess.PIPE, 
                      stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("Error: notify-send command not found.")
        print("Please install libnotify-bin package:")
        print("  sudo apt install libnotify-bin")
        return False

def get_input_with_timeout(timeout=0.05):
    """Non-blocking input check with support for single keypress detection"""
    try:
        # Set terminal to raw mode to read single characters
        import termios
        import tty
        from select import select
        
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            # Use select to check if there's input available
            rlist, _, _ = select([sys.stdin], [], [], timeout)
            if rlist:
                # Read a single character
                char = sys.stdin.read(1)
                # Convert to lowercase for case-insensitive commands
                return char.lower()
            return None
        finally:
            # Restore terminal settings no matter what
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except (Exception, termios.error) as e:
        # Fall back to the old method if we can't set raw mode
        # (for systems that don't support termios)
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return sys.stdin.readline().strip().lower()
        return None

def get_today_summary(include_in_progress=True):
    """Get a summary of today's tasks, both completed and in-progress"""
    log_file = get_day_log_file()
    if not log_file.exists():
        return "No tasks recorded today."
    
    completed_tasks = []
    abandoned_tasks = []
    in_progress_tasks = []
    total_completed_time = 0
    total_abandoned_time = 0
    
    with open(log_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Status"] == "Completed" and row["Duration (minutes)"]:
                completed_tasks.append(row)
                try:
                    total_completed_time += float(row["Duration (minutes)"])
                except ValueError:
                    pass
            elif row["Status"] == "Abandoned" and row["Duration (minutes)"]:
                abandoned_tasks.append(row)
                try:
                    total_abandoned_time += float(row["Duration (minutes)"])
                except ValueError:
                    pass
            elif include_in_progress and row["Status"] == "In Progress":
                in_progress_tasks.append(row)
    
    if not completed_tasks and not abandoned_tasks and not in_progress_tasks:
        return "No tasks recorded today."
    
    summary = "\n=== Today's Tasks ===\n"
    
    # Add completed tasks
    if completed_tasks:
        summary += "COMPLETED:\n"
        for i, task in enumerate(completed_tasks, 1):
            duration = float(task["Duration (minutes)"])
            summary += f"{i}. {task['Task']} - {duration:.1f} minutes\n"
        
        summary += f"\nCompleted: {len(completed_tasks)} tasks, {total_completed_time:.1f} minutes"
    else:
        summary += "No completed tasks yet.\n"
    
    # Add abandoned tasks
    if abandoned_tasks:
        summary += "\n\nABANDONED:\n"
        for i, task in enumerate(abandoned_tasks, 1):
            duration = float(task["Duration (minutes)"])
            summary += f"{i}. {task['Task']} - {duration:.1f} minutes\n"
        
        summary += f"\nAbandoned: {len(abandoned_tasks)} tasks, {total_abandoned_time:.1f} minutes"
    
    # Add in-progress tasks if requested
    if include_in_progress and in_progress_tasks:
        summary += "\n\nSTARTED BUT NOT COMPLETED:\n"
        for i, task in enumerate(in_progress_tasks, 1):
            start_time = task["Start Time"]
            summary += f"{i}. {task['Task']} - started at {start_time}\n"
    
    # Add completion rate if there are any completed or abandoned tasks
    if completed_tasks or abandoned_tasks:
        total_tasks = len(completed_tasks) + len(abandoned_tasks)
        completion_rate = len(completed_tasks) / total_tasks * 100 if total_tasks > 0 else 0
        summary += f"\n\nCompletion rate: {completion_rate:.1f}%"
    
    return summary

def print_help():
    """Print all available commands"""
    print("\nAvailable commands (press key - no Enter needed):")
    print("  p - Pause/resume the current task")
    print("  c - Complete the current task and start a new one")
    print("  x - Abandon the current task and start a new one")
    print("  a - Show list of abandoned tasks to potentially resume")
    print("  l - List all tasks for today")
    print("  t - Change the reminder timer interval")
    print("  h - Show this help message")
    print("  q - Quit Focus Tracker and show summary")
    print("\nSpecial commands (enter when prompted for a task):")
    print("  CLEAR - Delete all tasks for today (with confirmation)")
    print("")

def get_next_task():
    """Get the next task, handling empty input to show abandoned tasks"""
    while True:
        task = input("").strip()
        
        # Check for the CLEAR command
        if task.upper() == "CLEAR":
            confirm = input("\nWARNING: This will delete ALL tasks for today. Are you sure? (y/n): ").strip().lower()
            if confirm == 'y':
                clear_today_tasks()
                print("\nAll tasks for today have been cleared.")
            print("\nWhat are you working on next?")
            continue
            
        if task:
            return task
        
        # If empty input, show abandoned tasks
        abandoned_tasks = get_abandoned_tasks()
        if not abandoned_tasks:
            print("No abandoned tasks found. Please enter a task name.")
            continue
            
        print("\nAbandoned tasks:")
        for i, t in enumerate(abandoned_tasks, 1):
            print(f"{i}. {t['Task']}")
        
        try:
            selection = input("\nSelect task number to resume (or press Enter to enter a new task): ").strip()
            if not selection:
                continue
                
            task_num = int(selection)
            if 1 <= task_num <= len(abandoned_tasks):
                return abandoned_tasks[task_num-1]['Task']
            else:
                print("Invalid selection. Please enter a task name.")
        except ValueError:
            print("Invalid input. Please enter a task name.")

def handle_command(cmd, current_task, task_start_time, paused_time, is_paused):
    """Handle user commands during execution"""
    if cmd == "p":  # Pause/resume
        if is_paused:
            # Resume
            pause_duration = datetime.datetime.now() - paused_time
            task_start_time += pause_duration
            print(f"\nTask '{current_task}' resumed.")
            is_paused = False
        else:
            # Pause
            paused_time = datetime.datetime.now()
            print(f"\nTask '{current_task}' paused. Press 'p' again to resume.")
            is_paused = True
    
    elif cmd == "c" and not is_paused:  # Complete task
        end_time = datetime.datetime.now()
        duration = (end_time - task_start_time).total_seconds() / 60
        
        log_task(current_task, task_start_time, end_time, "Completed")
        print(f"\nTask '{current_task}' completed. Duration: {duration:.1f} minutes")
        
        # Start new task
        print("\nWhat are you working on next?")
        current_task = get_next_task()
        task_start_time = datetime.datetime.now()
        log_task(current_task, task_start_time)
        print(f"\nNew task started: '{current_task}'")
        send_notification("New Task Started", f"You're now working on: {current_task}")
    
    elif cmd == "x" and not is_paused:  # Abandon task
        end_time = datetime.datetime.now()
        duration = (end_time - task_start_time).total_seconds() / 60
        
        log_task(current_task, task_start_time, end_time, "Abandoned")
        print(f"\nTask '{current_task}' abandoned. Duration: {duration:.1f} minutes")
        
        # Start new task
        print("\nWhat are you working on next?")
        current_task = get_next_task()
        task_start_time = datetime.datetime.now()
        log_task(current_task, task_start_time)
        print(f"\nNew task started: '{current_task}'")
        send_notification("New Task Started", f"You're now working on: {current_task}")
    
    elif cmd == "a":  # Show abandoned tasks and possibly resume one
        abandoned_tasks = get_abandoned_tasks()
        if not abandoned_tasks:
            print("\nNo abandoned tasks found.")
        else:
            print("\nAbandoned tasks:")
            for i, task in enumerate(abandoned_tasks, 1):
                print(f"{i}. {task['Task']}")
            
            try:
                task_num = int(input("\nSelect task number to resume (or 0 to cancel): "))
                if task_num > 0 and task_num <= len(abandoned_tasks):
                    # If we're currently working on a task, mark it as abandoned
                    if current_task and not is_paused:
                        end_time = datetime.datetime.now()
                        log_task(current_task, task_start_time, end_time, "Abandoned")
                    
                    # Resume the abandoned task
                    current_task = abandoned_tasks[task_num-1]['Task']
                    task_start_time = datetime.datetime.now()
                    print(f"\nResuming task: '{current_task}'")
                    log_task(current_task, task_start_time)
                    send_notification("Task Resumed", f"You're now working on: {current_task}")
            except ValueError:
                print("Invalid selection.")
    
    elif cmd == "t":  # Change reminder interval
        config = load_config()
        current = config["reminder_interval"]
        try:
            new_interval = int(input(f"\nCurrent reminder interval is {current} minutes. Enter new interval: "))
            if new_interval < 1:
                print("Interval must be at least 1 minute.")
            else:
                config["reminder_interval"] = new_interval
                save_config(config)
                print(f"Reminder interval updated to {new_interval} minutes.")
        except ValueError:
            print("Please enter a valid number.")
    
    return current_task, task_start_time, paused_time, is_paused

def create_startup_script():
    """Create a startup script to launch focus tracker on boot"""
    desktop_file = Path.home() / ".config" / "autostart" / "focus-tracker.desktop"
    
    # Create autostart directory if it doesn't exist
    autostart_dir = desktop_file.parent
    if not autostart_dir.exists():
        autostart_dir.mkdir(parents=True)
    
    # Get path to current script
    script_path = os.path.abspath(sys.argv[0])
    
    # Create desktop entry file
    with open(desktop_file, 'w') as f:
        f.write(f"""[Desktop Entry]
Type=Application
Exec=gnome-terminal -- {script_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Focus Tracker
Comment=Start Focus Tracker on boot
""")
    
    # Make it executable
    os.chmod(desktop_file, 0o755)
    
    print(f"Startup script created at {desktop_file}")
    print("Focus Tracker will now start automatically on boot.")

def main():
    parser = argparse.ArgumentParser(description="Focus Tracker - Stay on task")
    parser.add_argument("--summary", action="store_true", help="Show today's task summary")
    parser.add_argument("--config", action="store_true", help="Edit configuration")
    parser.add_argument("--install", action="store_true", help="Install startup script")
    parser.add_argument("--idle", type=float, default=0.05, 
                        help="Idle time in seconds between checks (default: 0.05, higher values save CPU)")
    parser.add_argument("--show-data-dir", action="store_true", help="Show where data is stored")
    args = parser.parse_args()
    
    # Setup directories and files
    setup()
    initialize_day_log()
    
    if args.show_data_dir:
        print("\nFocus Tracker data is stored in the following locations:")
        print(f"  Configuration files: {CONFIG_DIR}")
        print(f"  Task logs and statistics: {DATA_DIR}")
        print(f"  Daily logs organized by month: {get_month_dir()}")
        print(f"  Statistics file: {STATS_FILE}")
        sys.exit(0)
    
    if args.summary:
        print(get_today_summary())
        sys.exit(0)
    
    if args.config:
        config = load_config()
        print("\nCurrent configuration:")
        for key, value in config.items():
            print(f"{key}: {value}")
        
        print("\nTo modify, edit the file:")
        print(CONFIG_FILE)
        sys.exit(0)
    
    if args.install:
        create_startup_script()
        sys.exit(0)
    
    if not check_dependencies():
        sys.exit(1)
    
    # Update statistics on startup
    update_statistics()
    
    config = load_config()
    
    print("\n🧠 Focus Tracker - Stay on your current task 🧠")
    print("Press 'h' anytime to see available commands")
    print("-" * 60)
    
    # Print help message at startup
    # print_help()  # Removed help message at startup
    
    # Get initial task
    print("\nWhat are you working on first?")
    current_task = get_next_task()
    task_start_time = datetime.datetime.now()
    log_task(current_task, task_start_time)
    
    print(f"\nTask started: '{current_task}'")
    print(f"You'll receive a reminder every {config['reminder_interval']} minutes")
    
    # Send initial notification
    send_notification("Task Started", f"You're now working on: {current_task}")
    
    # Setup variables for tracking state
    last_reminder_time = datetime.datetime.now()
    is_paused = False
    paused_time = None
    
    try:
        while True:
            # Check for user input
            cmd = get_input_with_timeout(args.idle)
            
            # Process command
            try:
                if cmd:
                    # Use lowercase for case-insensitive commands
                    cmd = cmd.lower()
                    
                    if cmd == 'l':  # List tasks
                        print("\n" + get_today_summary())
                        print(f"\nCurrent task: '{current_task}'" + (" (paused)" if is_paused else ""))
                    
                    elif cmd == 'h':  # Help
                        print_help()
                        
                    elif cmd in ['p', 'c', 't', 'x', 'a']:
                        current_task, task_start_time, paused_time, is_paused = handle_command(
                            cmd, current_task, task_start_time, paused_time, is_paused
                        )
                        last_reminder_time = datetime.datetime.now()  # Reset reminder timer after command
                    
                    elif cmd == 'q':  # Quit
                        raise KeyboardInterrupt
                    
                    elif cmd == '\x03':  # Ctrl+C (ASCII ETX)
                        raise KeyboardInterrupt
                    
                    elif cmd == ' ':  # Space bar - do nothing
                        pass
                    
                    elif cmd in ['\n', '\r']:  # Enter key - do nothing
                        pass
                    
                    elif cmd.isprintable():  # Show a message for unrecognized commands
                        print(f"\nUnrecognized command: '{cmd}'. Press 'h' for help.")
            except Exception as e:
                print(f"\nError processing command: {e}")
            
            # Skip reminders if paused
            if is_paused:
                continue
            
            # Check if it's time for a reminder
            current_time = datetime.datetime.now()
            config = load_config()  # Reload config to get updated reminder interval
            elapsed_seconds = (current_time - last_reminder_time).total_seconds()
            
            if elapsed_seconds >= config["reminder_interval"] * 60:
                # Send reminder
                send_notification(
                    "Focus Check", 
                    f"'{current_task}', are you on track?"
                )
                time_str = current_time.strftime("%H:%M")
                print(f"[{time_str}] Reminder: '{current_task}', are you on track?")
                last_reminder_time = current_time
            
    except KeyboardInterrupt:
        # Complete the current task if not paused
        if current_task and not is_paused:
            end_time = datetime.datetime.now()
            duration = (end_time - task_start_time).total_seconds() / 60
            log_task(current_task, task_start_time, end_time, "Completed")
            print(f"\nTask '{current_task}' ended. Duration: {duration:.1f} minutes")
        
        # Update statistics
        update_statistics()
        
        # Show summary
        print(get_today_summary())
        print("\nFocus Tracker stopped. Have a great day!")
        sys.exit(0)

if __name__ == "__main__":
    main()
