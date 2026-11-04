#!/usr/bin/env python
import logging
import time
import traceback
from argparse import ArgumentParser
from datetime import datetime

from rism import DemoManager
from rism.database import load_config

if __name__ == "__main__":
    LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    parser = ArgumentParser()
    parser.add_argument(
        "--loglevel", choices=LOG_LEVELS, help="set log level", default="WARN"
    )
    parser.add_argument("--robots", nargs="+", help="robot ID listr", default="dj_ri")
    parser.add_argument(
        "--host", help="hostname for config db", default=""
    )
    parser.add_argument("--port", help="port for config db", default=9010, type=int)
    parser.add_argument("--entry_point", help="scenario ID", default=None, type=str)
    parser.add_argument(
        "--no-auto-restart",
        action="store_true",
        help="disable automatic restart on error",
    )
    parser.add_argument(
        "--restart-delay",
        type=int,
        default=5,
        help="delay in seconds before restarting (default: 5)",
    )
    args = parser.parse_args()

    fmt = "%(asctime)s %(levelname)s %(name)s :%(message)s"
    logging.basicConfig(level=args.loglevel, format=fmt)
    logger = logging.getLogger(__name__)

    restart_count = 0

    while True:
        demo = None
        try:
            if restart_count > 0:
                logger.info(f"Restarting demo (attempt #{restart_count})...")

            config = load_config(args.host, args.port)
            demo = DemoManager(config, args.robots, args.entry_point)
            demo.run()

            # If run() exits normally, break the loop
            logger.info("Demo finished normally")
            break

        except KeyboardInterrupt:
            print("\nShutting down gracefully...:")
            error_traceback = traceback.format_exc()
            logger.error(error_traceback)
            if demo is not None:
                demo.kill_all()
            break

        except Exception as e:
            error_msg = f"[{datetime.now().isoformat()}] Error occurred: {e}\n"
            error_traceback = traceback.format_exc()

            print(error_msg)
            logger.error(error_msg)
            logger.error(error_traceback)

            if demo is not None:
                demo.kill_all()

            # Log to file
            with open("main_routine_log.txt", "a") as fout:
                fout.write(error_msg)
                fout.write(error_traceback)
                fout.write("\n" + "=" * 80 + "\n\n")

            # Check if auto-restart is disabled
            if args.no_auto_restart:
                logger.error("Auto-restart is disabled. Exiting.")
                raise e

            # Auto-restart logic
            restart_count += 1
            logger.info(f"Waiting {args.restart_delay} seconds before restarting...")
            time.sleep(args.restart_delay)
