#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Direct keyboard/mouse automation sender for PC WeChat.
No DLL injection, no web protocol.
"""

from __future__ import annotations

import argparse
import time

import psutil
import pyautogui
import pyperclip
import win32com.client
import win32gui
import win32process


def find_wechat_window() -> int:
    wins = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            pname = psutil.Process(pid).name()
        except Exception:
            return
        if "Weixin" in pname:
            wins.append((hwnd, title))

    win32gui.EnumWindows(cb, None)
    if not wins:
        raise RuntimeError("No visible WeChat window found.")

    for hwnd, title in wins:
        if title.strip() == "微信":
            return hwnd

    # Avoid non-chat windows like "朋友圈" when possible.
    for hwnd, title in wins:
        if "朋友圈" not in title:
            return hwnd

    return wins[0][0]


def focus_window(hwnd: int) -> None:
    win32gui.ShowWindow(hwnd, 9)
    shell = win32com.client.Dispatch("WScript.Shell")
    shell.SendKeys("%")
    win32gui.SetForegroundWindow(hwnd)


def send_text(target: str, text: str) -> None:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.12

    hwnd = find_wechat_window()
    focus_window(hwnd)
    time.sleep(0.7)

    # 1) Search target
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.35)
    pyperclip.copy(target)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.30)
    pyautogui.press("enter")
    time.sleep(0.8)

    # 2) Send message
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)
    pyautogui.press("enter")


def main() -> int:
    p = argparse.ArgumentParser(description="Send one message through desktop WeChat automation.")
    p.add_argument("--target", required=True, help="Contact name shown in WeChat")
    p.add_argument("--text", required=True, help="Message to send")
    args = p.parse_args()

    send_text(args.target, args.text)
    print("MESSAGE_SENT")
    print(f"target={args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
