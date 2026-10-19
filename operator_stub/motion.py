"""Разные ограниченные динамические модели для учебной 2D-среды.

Параметры выбраны для наблюдаемого поведения, не идентифицированы на роботах.
БЭК здесь — одновинтовой корпус с рулём; катамаран с раздельными движителями
может разворачиваться на месте и потребует другой модели.
"""

from __future__ import annotations

from copy import deepcopy
import math

from .models import Pose
from .world import HEIGHT, WIDTH, is_free


def approach(value: float, target: float, max_delta: float) -> float:
    return value + max(-max_delta, min(max_delta, target - value))


class MotionModel:
    INTEGRATION_STEP = 0.01

    def __init__(self, kind: str, initial_pose: Pose):
        self.kind = kind
        self.pose = deepcopy(initial_pose)
        self.max_speed = {"БПЛА": 6.0, "БЭК": 4.0}.get(kind, 3.0)
        self.max_yaw_rate = {"БПЛА": 90.0, "БЭК": 20.0}.get(kind, 90.0)
        self.radius = {"БПЛА": 0.5, "БЭК": 1.0}.get(kind, 0.55)
        self.forward_speed = self.yaw_rate_deg_s = 0.0
        self.vx = self.vy = 0.0
        self.distance_travelled = 0.0
        self.collision = False

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def halt(self) -> None:
        self.forward_speed = self.yaw_rate_deg_s = self.vx = self.vy = 0.0

    def step(self, forward: float, turn: float, dt: float) -> None:
        if dt <= 0:
            return
        steps = max(1, math.ceil(dt / self.INTEGRATION_STEP - 1e-10))
        step = dt / steps
        self.collision = False
        for _ in range(steps):
            self._integrate(forward, turn, step)
            if self.collision:
                break

    def _integrate(self, forward: float, turn: float, dt: float) -> None:
        old_heading = self.pose.heading
        if self.kind == "БЭК":
            target_speed = forward * (self.max_speed if forward >= 0 else 2.0)
            acceleration = 0.55 if abs(target_speed) > abs(self.forward_speed) else 0.35
            self.forward_speed = approach(self.forward_speed, target_speed, acceleration * dt)
            # Reduced first-order Nomoto: T*r_dot + r = K*delta. A rudder
            # has no authority in still water, and reverses yaw effect in astern.
            authority = min(1.0, abs(self.forward_speed) / 2.0)
            direction = 1.0 if self.forward_speed >= 0 else -1.0
            target_yaw = turn * self.max_yaw_rate * authority * direction
            tau = 1.6 if turn else 2.8
            filtered = self.yaw_rate_deg_s + (target_yaw - self.yaw_rate_deg_s) * (-math.expm1(-dt / tau))
            self.yaw_rate_deg_s = approach(self.yaw_rate_deg_s, filtered, 12.0 * dt)
        else:
            angular_acceleration = 120.0 if self.kind == "БПЛА" else 180.0
            self.yaw_rate_deg_s = approach(self.yaw_rate_deg_s, turn * self.max_yaw_rate,
                                          angular_acceleration * dt)
            if self.kind != "БПЛА":
                target_speed = forward * self.max_speed
                acceleration = 1.5 if abs(target_speed) > abs(self.forward_speed) else 2.5
                self.forward_speed = approach(self.forward_speed, target_speed, acceleration * dt)
        self.pose.heading = (old_heading + self.yaw_rate_deg_s * dt) % 360.0
        angle = math.radians(old_heading + self.yaw_rate_deg_s * dt * 0.5)
        if self.kind == "БПЛА":
            # Velocity vector lives in world coordinates: rotating yaw cannot
            # instantly rotate the craft's momentum. Height is held at 8 m.
            target_vx = forward * self.max_speed * math.cos(angle)
            target_vy = forward * self.max_speed * math.sin(angle)
            delta_x, delta_y = target_vx - self.vx, target_vy - self.vy
            delta = math.hypot(delta_x, delta_y)
            factor = min(1.0, 2.0 * dt / delta) if delta else 0.0
            self.vx += delta_x * factor
            self.vy += delta_y * factor
        else:
            self.vx = self.forward_speed * math.cos(angle)
            self.vy = self.forward_speed * math.sin(angle)
        x = self.pose.x + self.vx * dt
        y = self.pose.y + self.vy * dt
        if not is_free(x, y, self.radius):
            # Collision is a simulator interlock, not an autonomous planner.
            self.collision = True
            self.halt()
            return
        self.distance_travelled += math.hypot(x - self.pose.x, y - self.pose.y)
        self.pose.x, self.pose.y = x, y
