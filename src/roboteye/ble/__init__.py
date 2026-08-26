"""Bluetooth do robo: o celular fala com o Pi direto, sem ESP32 no meio."""

from roboteye.ble.nus import NUS_RX, NUS_SERVICE, NUS_TX, PonteBLE

__all__ = ["NUS_RX", "NUS_SERVICE", "NUS_TX", "PonteBLE"]
