"""CLI: python -m app.channels.weixin login|worker"""
import argparse

from .auth import login
from .worker import run

parser = argparse.ArgumentParser(description="序时课表微信 ClawBot 渠道")
parser.add_argument("command", choices=("login", "worker"))
args = parser.parse_args()
login() if args.command == "login" else run()
