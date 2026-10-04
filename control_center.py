import os
import sys
import subprocess

BASE_DIR = os.path.expanduser("~/Desktop/psych_digest")

def clear():
    os.system("clear")

def banner():
    print("\033[1;36m==================================================\033[0m")
    print("\033[1;37m        PSYCHOLOGY RESEARCH DIGEST MANAGER       \033[0m")
    print("\033[1;36m==================================================\033[0m")
    print()

def run_cmd(cmd_str, title):
    clear()
    banner()
    print(f"\033[1;33m>>> Starting: {title}...\033[0m\n")
    try:
        subprocess.run(cmd_str, shell=True, cwd=BASE_DIR, check=True)
        print(f"\n\033[1;32m>>> Success: {title} complete!\033[0m")
    except subprocess.CalledProcessError as e:
        print(f"\n\033[1;31m>>> Process returned error code: {e.returncode}\033[0m")
    except Exception as e:
        print(f"\n\033[1;31m>>> Error: {e}\033[0m")
    print("\nPress [Enter] to return to the menu...")
    input()

def main():
    while True:
        clear()
        banner()
        print("  \033[1;34m[1]\033[0m 🔄  Sync With Cloud (Pull overnight episodes & fix conflicts)")
        print("  \033[1;32m[2]\033[0m ⚡  Run 1 On-Demand Episode (Spotlight paper)")
        print("  \033[1;33m[3]\033[0m 📚  Run Full Batch (7 Papers)")
        print("  \033[1;35m[4]\033[0m 🎙️   Run Weekly Recap")
        print("  \033[1;37m[5]\033[0m 📂  Open psych_digest Folder in Finder")
        print("  \033[1;37m[6]\033[0m 🌐  Open Live Podcast Feed in Browser")
        print("  \033[1;31m[q]\033[0m ❌  Quit")
        print()
        choice = input("\033[1mSelect an option [1-6, q]: \033[0m").strip().lower()

        if choice == '1':
            run_cmd("./sync.sh", "Sync with Cloud")
        elif choice == '2':
            run_cmd("python3 generate_single.py && ./sync.sh", "Single On-Demand Episode")
        elif choice == '3':
            run_cmd("python3 generate_digest.py && ./sync.sh", "Full 7-Paper Batch")
        elif choice == '4':
            run_cmd("python3 generate_recap.py && ./sync.sh", "Weekly Recap")
        elif choice == '5':
            subprocess.run(["open", BASE_DIR])
        elif choice == '6':
            subprocess.run(["open", "https://feeeeeeeeeeeeeeeeeee.github.io/psych-digest-feed/feed.xml"])
        elif choice in ('q', 'exit'):
            clear()
            print("Goodbye!\n")
            sys.exit(0)

if __name__ == "__main__":
    main()
