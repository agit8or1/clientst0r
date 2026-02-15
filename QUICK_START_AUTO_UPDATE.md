# Quick Start: Enable Auto-Updates

## One Command Setup

```bash
cd /home/administrator
./scripts/install_auto_update.sh
```

That's it! After this runs, all future updates are **100% automatic**.

## What Happens Next

Starting now, every day at 2 AM:
1. ✅ Checks GitHub for new releases
2. ✅ Downloads latest code automatically
3. ✅ Runs database migrations automatically
4. ✅ Restarts all services automatically
5. ✅ Logs everything

**You never have to update manually again!**

## Verify It's Working

Check status:
```bash
sudo systemctl status clientst0r-auto-update.timer
```

View next scheduled run:
```bash
sudo systemctl list-timers | grep clientst0r
```

## Test It Now (Optional)

Don't want to wait until 2 AM? Run it now:

```bash
sudo systemctl start clientst0r-auto-update.service
```

Watch it work:
```bash
tail -f /var/log/clientst0r/auto-update.log
```

## What You Get

- **v2.50.1** → Applied automatically
- **v2.51.0** → Applied automatically
- **v3.0.0** → Applied automatically
- **All future versions** → Applied automatically

Migrations? **Automatic.**
Service restarts? **Automatic.**
Dependency updates? **Automatic.**

**Everything? AUTOMATIC!** 🚀

## Need Help?

Full documentation: `AUTO_UPDATE.md`

Commands:
- Check status: `sudo systemctl status clientst0r-auto-update.timer`
- View logs: `tail -f /var/log/clientst0r/auto-update.log`
- Disable: `sudo systemctl disable clientst0r-auto-update.timer`
- Enable: `sudo systemctl enable clientst0r-auto-update.timer`
