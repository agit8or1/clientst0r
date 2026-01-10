#!/usr/bin/env python3
"""
Screenshot Selector - Interactive tool to select screenshots for GitHub
"""
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime


class ScreenshotSelector:
    """Interactive screenshot selection tool"""

    def __init__(self, screenshot_dir='screenshots'):
        self.screenshot_dir = Path(screenshot_dir)
        self.manifest_path = self.screenshot_dir / 'manifest.json'
        self.manifest = None
        self.screenshots = []

    def load_manifest(self):
        """Load the screenshot manifest"""
        if not self.manifest_path.exists():
            print(f"❌ Manifest not found: {self.manifest_path}")
            return False

        with open(self.manifest_path, 'r') as f:
            self.manifest = json.load(f)
            self.screenshots = self.manifest.get('screenshots', [])

        print(f"📄 Loaded {len(self.screenshots)} screenshots")
        return True

    def save_manifest(self):
        """Save the updated manifest"""
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)
        print("💾 Manifest saved")

    def display_screenshot(self, screenshot):
        """Display a screenshot using system viewer"""
        filepath = self.screenshot_dir / screenshot['filename']
        if filepath.exists():
            # Try different image viewers
            for viewer in ['xdg-open', 'eog', 'feh', 'display']:
                try:
                    subprocess.Popen([viewer, str(filepath)],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                    return True
                except FileNotFoundError:
                    continue
            print(f"⚠️  Could not open image viewer. File: {filepath}")
        return False

    def print_screenshot_info(self, idx, screenshot):
        """Print information about a screenshot"""
        selected = "✅" if screenshot.get('selected', False) else "⬜"
        print(f"\n{selected} [{idx+1}] {screenshot['name']}")
        print(f"     Title: {screenshot['title']}")
        print(f"     URL: {screenshot['url']}")
        print(f"     File: {screenshot['filename']}")

    def interactive_selection(self):
        """Interactive screenshot selection"""
        print("\n" + "="*60)
        print("Screenshot Selector for GitHub")
        print("="*60 + "\n")

        while True:
            # Show current selection status
            selected_count = sum(1 for s in self.screenshots if s.get('selected', False))
            print(f"\n📊 Selected: {selected_count}/{len(self.screenshots)} screenshots\n")

            # Show menu
            print("Options:")
            print("  1. List all screenshots")
            print("  2. View and select screenshots individually")
            print("  3. Select all")
            print("  4. Deselect all")
            print("  5. Select by number range (e.g., 1-10)")
            print("  6. Export selected screenshots")
            print("  7. Show selected screenshots")
            print("  q. Quit")

            choice = input("\nYour choice: ").strip().lower()

            if choice == 'q':
                break
            elif choice == '1':
                self.list_all()
            elif choice == '2':
                self.individual_selection()
            elif choice == '3':
                self.select_all()
            elif choice == '4':
                self.deselect_all()
            elif choice == '5':
                self.select_range()
            elif choice == '6':
                self.export_selected()
            elif choice == '7':
                self.show_selected()
            else:
                print("Invalid choice")

    def list_all(self):
        """List all screenshots"""
        print("\n" + "-"*60)
        for idx, screenshot in enumerate(self.screenshots):
            self.print_screenshot_info(idx, screenshot)
        print("-"*60)

    def individual_selection(self):
        """Select screenshots one by one"""
        for idx, screenshot in enumerate(self.screenshots):
            self.print_screenshot_info(idx, screenshot)

            # Ask to view
            view = input("\n  View this screenshot? (y/n/skip): ").strip().lower()
            if view == 'y':
                self.display_screenshot(screenshot)

            # Ask to select
            select = input("  Select this screenshot? (y/n/skip/quit): ").strip().lower()

            if select == 'quit':
                break
            elif select == 'y':
                screenshot['selected'] = True
                print("  ✅ Selected")
            elif select == 'n':
                screenshot['selected'] = False
                print("  ⬜ Deselected")

        self.save_manifest()

    def select_all(self):
        """Select all screenshots"""
        for screenshot in self.screenshots:
            screenshot['selected'] = True
        self.save_manifest()
        print(f"✅ Selected all {len(self.screenshots)} screenshots")

    def deselect_all(self):
        """Deselect all screenshots"""
        for screenshot in self.screenshots:
            screenshot['selected'] = False
        self.save_manifest()
        print(f"⬜ Deselected all screenshots")

    def select_range(self):
        """Select a range of screenshots"""
        range_str = input("\nEnter range (e.g., 1-10, 5-8, 12-15): ").strip()
        try:
            start, end = range_str.split('-')
            start, end = int(start) - 1, int(end)  # Convert to 0-indexed

            if 0 <= start < end <= len(self.screenshots):
                for idx in range(start, end):
                    self.screenshots[idx]['selected'] = True
                self.save_manifest()
                print(f"✅ Selected screenshots {start+1} to {end}")
            else:
                print("❌ Invalid range")
        except Exception as e:
            print(f"❌ Invalid input: {e}")

    def show_selected(self):
        """Show all selected screenshots"""
        selected = [s for s in self.screenshots if s.get('selected', False)]

        if not selected:
            print("\n⚠️  No screenshots selected")
            return

        print("\n" + "-"*60)
        print(f"Selected Screenshots ({len(selected)}):")
        print("-"*60)
        for idx, screenshot in enumerate(selected):
            print(f"\n✅ [{idx+1}] {screenshot['name']}")
            print(f"     Title: {screenshot['title']}")
            print(f"     File: {screenshot['filename']}")
        print("-"*60)

    def export_selected(self):
        """Export selected screenshots to a separate directory"""
        selected = [s for s in self.screenshots if s.get('selected', False)]

        if not selected:
            print("\n⚠️  No screenshots selected for export")
            return

        # Create export directory
        export_dir = Path('screenshots_selected')
        export_dir.mkdir(exist_ok=True)

        print(f"\n📤 Exporting {len(selected)} screenshots...")

        # Copy selected screenshots
        for screenshot in selected:
            src = self.screenshot_dir / screenshot['filename']
            dst = export_dir / screenshot['filename']

            if src.exists():
                shutil.copy2(src, dst)
                print(f"  ✓ Copied: {screenshot['filename']}")
            else:
                print(f"  ✗ Not found: {screenshot['filename']}")

        # Create manifest for selected
        export_manifest = {
            'exported_at': datetime.now().isoformat(),
            'source_dir': str(self.screenshot_dir),
            'total_selected': len(selected),
            'screenshots': selected
        }

        manifest_path = export_dir / 'manifest.json'
        with open(manifest_path, 'w') as f:
            json.dump(export_manifest, f, indent=2)

        # Create README
        readme_path = export_dir / 'README.md'
        with open(readme_path, 'w') as f:
            f.write(f"# HuduGlue Screenshots\n\n")
            f.write(f"Selected screenshots for documentation.\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Total Screenshots:** {len(selected)}\n\n")
            f.write("## Screenshots\n\n")

            for idx, screenshot in enumerate(selected, 1):
                f.write(f"{idx}. **{screenshot['title']}**\n")
                f.write(f"   - File: `{screenshot['filename']}`\n")
                f.write(f"   - URL: `{screenshot['url']}`\n")
                f.write(f"   ![{screenshot['title']}]({screenshot['filename']})\n\n")

        print(f"\n✅ Export complete!")
        print(f"📁 Location: {export_dir.absolute()}")
        print(f"📄 README created: {readme_path}")

    def run(self):
        """Run the screenshot selector"""
        if not self.load_manifest():
            return

        self.interactive_selection()

        print("\n" + "="*60)
        print("Thank you for using Screenshot Selector!")
        print("="*60 + "\n")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Select screenshots for GitHub documentation')
    parser.add_argument('--dir', default='screenshots', help='Screenshot directory')

    args = parser.parse_args()

    selector = ScreenshotSelector(screenshot_dir=args.dir)
    selector.run()
