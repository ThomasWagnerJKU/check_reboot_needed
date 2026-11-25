"""Tests for check_reboot_needed with a fake file tree (--root) and a fake zypper."""
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(os.path.dirname(HERE), "check_reboot_needed")
DAY = 86400


class CheckRebootNeeded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        for sub in ("boot", "run", "proc", "bin"):
            os.mkdir(os.path.join(self.root, sub))
        self.write("proc/uptime", "172800.00 1000.00\n")         # up 2 days

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text="", age_days=None):
        path = os.path.join(self.root, rel)
        with open(path, "w") as handle:
            handle.write(text)
        if age_days is not None:
            stamp = time.time() - age_days * DAY
            os.utime(path, (stamp, stamp))
        return path

    def zypper(self, rc):
        path = self.write("bin/zypper", "#!/bin/sh\necho 'needs-rebooting answer'\nexit %d\n" % rc)
        os.chmod(path, 0o755)
        return path

    def run_plugin(self, release, *args, zypper=None):
        cmd = [sys.executable, PLUGIN, "--root", self.root, "--release", release]
        cmd += ["--zypper", zypper] if zypper else ["--no-zypper"]
        res = subprocess.run(cmd + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.returncode, res.stdout, res.stderr

    def test_running_newest_kernel(self):
        self.write("boot/vmlinuz-6.12.117+deb13-amd64")
        self.write("boot/vmlinuz-6.12.118+deb13-amd64")
        rc, out, _ = self.run_plugin("6.12.118+deb13-amd64")
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.startswith("REBOOT OK - no reboot pending, up 2.0 days |"), out)
        self.assertIn("pending_days=0.00;0;;0; uptime_days=2.00;;;0;", out)

    def test_newer_kernel_warns_at_once_by_default(self):
        self.write("boot/vmlinuz-6.12.117+deb13-amd64")
        self.write("boot/vmlinuz-6.12.118+deb13-amd64")
        rc, out, _ = self.run_plugin("6.12.117+deb13-amd64")
        self.assertEqual(rc, 1, out)
        self.assertIn("REBOOT WARNING - reboot pending for 0.0 days", out)
        self.assertIn("kernel 6.12.118+deb13-amd64 installed, running 6.12.117+deb13-amd64", out)

    def test_warning_threshold_in_days(self):
        self.write("boot/vmlinuz-6.12.118+deb13-amd64")
        rc, out, _ = self.run_plugin("6.12.117+deb13-amd64", "-w", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("REBOOT OK - reboot pending for 0.0 days", out)
        self.assertIn("pending_days=0.00;7;;0;", out)

    def test_flag_age_gives_warning_and_critical(self):
        self.write("run/reboot-required", "*** System restart required ***\n", age_days=10)
        self.write("run/reboot-required.pkgs", "linux-base\nlinux-image-6.8.0-151-generic\nlinux-base\n")
        rc, out, _ = self.run_plugin("6.8.0-151-generic", "-w", "7", "-c", "30")
        self.assertEqual(rc, 1, out)
        self.assertIn("reboot pending for 10.0 days", out)
        self.assertIn("flag /run/reboot-required (linux-base, linux-image-6.8.0-151-generic)", out)
        rc, out, _ = self.run_plugin("6.8.0-151-generic", "-w", "7", "-c", "9")
        self.assertEqual(rc, 2, out)

    def test_oldest_reason_counts_others_in_long_output(self):
        self.write("boot/vmlinuz-6.8.0-151-generic")                          # installed now
        self.write("run/reboot-required", "", age_days=3)
        rc, out, _ = self.run_plugin("6.8.0-149-generic", "-w", "7")
        self.assertEqual(rc, 0, out)
        first, second = out.splitlines()[:2]
        self.assertIn("reboot pending for 3.0 days", first)
        self.assertIn("- flag /run/reboot-required (since", first)
        self.assertTrue(second.startswith("kernel 6.8.0-151-generic installed, running 6.8.0-149-generic"), out)

    def test_other_flavors_and_backups_are_ignored(self):
        self.write("boot/vmlinuz-6.12.0-160000.41-default")
        self.write("boot/vmlinuz-6.12.0-160000.45-rt")              # other flavor
        self.write("boot/vmlinuz-6.12.0-160000.44-default.old")     # backup copy
        rc, out, _ = self.run_plugin("6.12.0-160000.41-default")
        self.assertEqual(rc, 0, out)

    def test_version_numbers_compare_numerically(self):
        self.write("boot/vmlinuz-6.12.99+deb13-amd64")
        self.write("boot/vmlinuz-6.12.118+deb13-amd64")
        rc, out, _ = self.run_plugin("6.12.99+deb13-amd64")
        self.assertIn("kernel 6.12.118+deb13-amd64 installed", out)
        rc, out, _ = self.run_plugin("6.12.118+deb13-amd64")
        self.assertEqual(rc, 0, out)

    def test_raspberry_pi_flavor(self):
        self.write("boot/vmlinuz-6.18.60+rpt-rpi-v8")
        self.write("boot/vmlinuz-6.18.61+rpt-rpi-2712")             # Pi 5 kernel, other flavor
        rc, out, _ = self.run_plugin("6.18.60+rpt-rpi-v8")
        self.assertEqual(rc, 0, out)
        self.write("boot/vmlinuz-6.18.61+rpt-rpi-v8")
        rc, out, _ = self.run_plugin("6.18.60+rpt-rpi-v8")
        self.assertEqual(rc, 1, out)

    def test_no_kernel_images_is_ok(self):
        rc, out, _ = self.run_plugin("6.18.60+rpt-rpi-v8")
        self.assertEqual(rc, 0, out)
        self.assertIn("no reboot pending", out)

    def test_zypper_needs_rebooting(self):
        self.write("boot/vmlinuz-6.12.0-160000.41-default")
        rc, out, _ = self.run_plugin("6.12.0-160000.41-default", zypper=self.zypper(0))
        self.assertEqual(rc, 0, out)
        rc, out, _ = self.run_plugin("6.12.0-160000.41-default", zypper=self.zypper(102))
        self.assertEqual(rc, 1, out)
        self.assertIn("zypper needs-rebooting: core libraries or services were updated", out)

    def test_zypper_error_is_unknown_without_other_reasons(self):
        rc, out, _ = self.run_plugin("6.12.0-160000.41-default", zypper=self.zypper(4))
        self.assertEqual(rc, 3, out)
        self.assertIn("REBOOT UNKNOWN - zypper needs-rebooting exited 4: needs-rebooting answer", out)

    def test_zypper_error_is_reported_with_other_reasons(self):
        self.write("run/reboot-needed", "", age_days=1)
        rc, out, _ = self.run_plugin("6.12.0-160000.41-default", zypper=self.zypper(4))
        self.assertEqual(rc, 1, out)
        self.assertIn("flag /run/reboot-needed", out)
        self.assertIn("zypper needs-rebooting exited 4", out.splitlines()[1])

    def test_critical_below_warning_is_rejected(self):
        rc, out, _ = self.run_plugin("6.8.0-151-generic", "-w", "7", "-c", "3")
        self.assertEqual(rc, 3)
        self.assertIn("REBOOT UNKNOWN - -c must not be smaller than -w", out)
        rc, out, _ = self.run_plugin("6.8.0-151-generic", "-w", "-1")
        self.assertEqual(rc, 3)

    def test_version(self):
        res = subprocess.run([sys.executable, PLUGIN, "-V"], stdout=subprocess.PIPE, text=True)
        self.assertRegex(res.stdout, r"^check_reboot_needed \d+\.\d+")


if __name__ == "__main__":
    unittest.main()
