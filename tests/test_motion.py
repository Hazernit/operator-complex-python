"""Проверяем наблюдаемые физические ограничения, а не копию формул."""

import math
import unittest

from operator_stub.adapters.mock import MockAdapter
from operator_stub.models import MISSION_COMPLETED, MISSION_PAUSED, Point, Pose
from operator_stub.motion import MotionModel
from operator_stub.service import OperatorService
from operator_stub.world import raycast


def adapter(kind="БЭК", x=18, y=10):
    result = MockAdapter({"id": "test", "name": "Учебная модель", "kind": kind,
                          "initial_pose": {"x": x, "y": y, "heading": 0}})
    result.connect()
    return result


class MotionTests(unittest.TestCase):
    def test_boat_rudder_cannot_turn_stationary_hull(self):
        boat = MotionModel("БЭК", Pose(10, 10, 0))
        boat.step(0, 1, 8)
        self.assertEqual(boat.pose, Pose(10, 10, 0))
        self.assertEqual(boat.speed, 0)

    def test_ground_differential_drive_can_turn_in_place(self):
        ground = MotionModel("НРТК", Pose(10, 10, 0))
        ground.step(0, 1, 1)
        self.assertGreater(ground.pose.heading, 40)
        self.assertEqual((ground.pose.x, ground.pose.y), (10, 10))

    def test_boat_turn_is_bounded_and_never_a_90_degree_jump(self):
        boat = MotionModel("БЭК", Pose(10, 10, 0))
        boat.step(1, 0, 4)
        for _ in range(100):
            before = boat.pose.heading
            boat.step(1, 1, 0.05)
            delta = (boat.pose.heading - before + 180) % 360 - 180
            self.assertLessEqual(abs(delta), 1.0 + 1e-9)
            self.assertLessEqual(abs(boat.yaw_rate_deg_s), 20.0)
        self.assertGreater(boat.pose.y, 10)

    def test_releasing_boat_throttle_causes_observable_coasting(self):
        boat = adapter()
        boat.set_velocity(1, 0)
        boat.tick(4)
        before = boat.tick(0)
        boat.set_velocity(0, 0)
        after = boat.tick(0.5)
        self.assertGreater(after.pose.x, before.pose.x)
        self.assertGreater(after.speed, 0)
        self.assertLess(after.speed, before.speed)

    def test_explicit_simulator_halt_freezes_boat(self):
        boat = adapter()
        boat.set_velocity(1, 0.5)
        boat.tick(4)
        boat.halt()
        before = boat.tick(0)
        after = boat.tick(2)
        self.assertEqual(before.pose, after.pose)
        self.assertEqual(after.speed, 0)

    def test_service_neutral_preserves_boat_coasting_beyond_watchdog_interval(self):
        service = OperatorService()
        platform_id = "demo-usv"
        service.connect(platform_id)
        for _ in range(20):
            service.set_velocity(platform_id, 1, 0)
            service.tick(0.1)
        state = service.platforms[platform_id]
        before_x, before_speed = state.pose.x, state.speed
        self.assertGreater(before_speed, 1)
        service.set_velocity(platform_id, 0, 0)
        service.tick(0.8)
        self.assertGreater(state.pose.x, before_x)
        self.assertGreater(state.speed, 0)
        self.assertLess(state.speed, before_speed)
        self.assertEqual(state.mode, "Торможение")
        midway_x = state.pose.x
        service.tick(0.2)
        self.assertGreater(state.pose.x, midway_x)
        service.stop(platform_id)
        stopped_pose = (state.pose.x, state.pose.y, state.pose.heading)
        service.tick(1)
        self.assertEqual(state.speed, 0)
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), stopped_pose)

    def test_service_expired_nonzero_command_still_halts_boat(self):
        service = OperatorService()
        platform_id = "demo-usv"
        service.connect(platform_id)
        for _ in range(20):
            service.set_velocity(platform_id, 1, 0)
            service.tick(0.1)
        state = service.platforms[platform_id]
        self.assertGreater(state.speed, 1)
        service.tick(0.8)
        self.assertEqual(state.speed, 0)
        stopped_pose = (state.pose.x, state.pose.y, state.pose.heading)
        service.tick(1)
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), stopped_pose)
        self.assertTrue(any("Истёк срок ручной команды" in event.message for event in service.events))

    def test_uav_yaw_does_not_instantly_rotate_world_velocity(self):
        drone = MotionModel("БПЛА", Pose(10, 10, 0))
        drone.step(1, 0, 2)
        before_vx = drone.vx
        drone.step(1, 1, 0.05)
        self.assertGreater(drone.vx, before_vx - 0.11)
        self.assertLess(math.hypot(drone.vx - before_vx, drone.vy), 0.101)

    def test_motion_is_consistent_across_public_time_steps(self):
        for kind in ("БПЛА", "НРТК", "БЭК"):
            with self.subTest(kind=kind):
                a = MotionModel(kind, Pose(10, 10, 0))
                b = MotionModel(kind, Pose(10, 10, 0))
                for _ in range(20):
                    a.step(0.6, 0.2, 0.2)
                for _ in range(80):
                    b.step(0.6, 0.2, 0.05)
                self.assertAlmostEqual(a.pose.x, b.pose.x, places=8)
                self.assertAlmostEqual(a.pose.y, b.pose.y, places=8)
                self.assertAlmostEqual(a.pose.heading, b.pose.heading, places=8)

    def test_lidar_echo_comes_from_geometric_obstacle(self):
        robot = adapter("НРТК", x=18, y=20)
        frame = robot.tick(0).sensor_frame
        forward = next(reading for reading in frame.readings
                       if reading.sensor == "lidar" and reading.angle_deg == 0)
        self.assertTrue(forward.hit)
        self.assertAlmostEqual(forward.range_m, 14.0, places=3)
        self.assertAlmostEqual(raycast(18, 20, 0, 30), 14)

    def test_sonar_is_one_cone_echo_with_bearing_uncertainty(self):
        frame = adapter().tick(0).sensor_frame
        sonars = [reading for reading in frame.readings if reading.sensor == "sonar"]
        self.assertEqual(len(sonars), 1)
        self.assertGreater(sonars[0].fov_deg, 0)

    def test_sensor_pose_is_separate_from_simulator_truth(self):
        robot = adapter("НРТК")
        robot.set_velocity(0.7, 0)
        snapshot = robot.tick(1)
        self.assertEqual(snapshot.pose, snapshot.sensor_frame.pose)
        self.assertNotEqual(snapshot.pose, snapshot.true_pose)
        self.assertLess(math.hypot(snapshot.pose.x - snapshot.true_pose.x,
                                   snapshot.pose.y - snapshot.true_pose.y), 0.03)

    def test_each_platform_completes_a_clear_straight_route(self):
        service = OperatorService()
        for platform_id, state in service.platforms.items():
            service.connect(platform_id)
            service.set_route(platform_id, [Point(state.pose.x + 10, state.pose.y)])
            service.start_mission(platform_id)
        for _ in range(300):
            service.tick(0.05)
            if all(state.mission_status == MISSION_COMPLETED for state in service.platforms.values()):
                break
        self.assertTrue(all(state.mission_status == MISSION_COMPLETED for state in service.platforms.values()))

    def test_boat_completes_corner_route_with_bounded_heading_rate(self):
        service = OperatorService()
        service.connect("demo-usv")
        service.set_route("demo-usv", [Point(45, 10), Point(45, 30)])
        service.start_mission("demo-usv")
        state = service.platforms["demo-usv"]
        for _ in range(1000):
            before = state.pose.heading
            service.tick(0.05)
            delta = (state.pose.heading - before + 180) % 360 - 180
            self.assertLessEqual(abs(delta), 1.01)
            if state.mission_status == MISSION_COMPLETED:
                break
        self.assertEqual(state.mission_status, MISSION_COMPLETED)
        self.assertLess(math.hypot(state.pose.x - 45, state.pose.y - 30), 1)

    def test_collision_interlock_pauses_mission_instead_of_crossing_wall(self):
        robot = adapter("НРТК", x=30, y=20)
        service = OperatorService(adapters=[robot])
        service.connect("test")
        service.set_route("test", [Point(45, 20)])
        service.start_mission("test")
        state = service.platforms["test"]
        for _ in range(100):
            service.tick(0.05)
            if state.mission_status == MISSION_PAUSED:
                break
        self.assertEqual(state.mission_status, MISSION_PAUSED)
        self.assertLess(state.true_pose.x, 32)
        self.assertEqual(state.speed, 0)
        self.assertTrue(any("Контакт" in event.message for event in service.events))
        pose_after_collision = (state.pose.x, state.pose.y, state.pose.heading)
        service.tick(1.0)
        self.assertTrue(state.collision)
        self.assertEqual(state.mission_status, MISSION_PAUSED)
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), pose_after_collision)

    def test_collision_warning_needs_an_operator_action_to_clear(self):
        service = OperatorService()
        platform_id = "demo-ugv"
        service.connect(platform_id)
        state = service.platforms[platform_id]
        state.collision = True
        service.set_velocity(platform_id, 0, 0)
        service.tick(1)
        self.assertTrue(state.collision)
        service.stop(platform_id)
        self.assertTrue(state.collision)
        service.set_velocity(platform_id, -0.3, 0)
        self.assertFalse(state.collision)
        state.collision = True
        service.set_velocity(platform_id, -0.3, 0)
        self.assertTrue(state.collision)  # Held-key heartbeat is no acknowledgement.
        service.set_velocity(platform_id, 0, 0)
        self.assertTrue(state.collision)
        service.set_velocity(platform_id, -0.3, 0)
        self.assertFalse(state.collision)
        state.collision = True
        service.cancel_mission(platform_id)
        self.assertFalse(state.collision)
        state.collision = True
        service.reset(platform_id)
        self.assertFalse(state.collision)
        state.collision = True
        service.set_route(platform_id, [Point(25, 30)])
        service.start_mission(platform_id)
        self.assertFalse(state.collision)
        service.pause_mission(platform_id)
        state.collision = True
        service.resume_mission(platform_id)
        self.assertFalse(state.collision)


if __name__ == "__main__":
    unittest.main()
