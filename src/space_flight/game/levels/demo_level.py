import numpy as np

from space_flight.bot import spawn_bot
from space_flight.player import Player
from space_flight.scenes.scenes import scene_factory


def build_demo_level(game):
    """
    A function to build the demo level
    """

    """
    Launch music
    """
    # music = game.app.loader.loadMusic(
    # DATAFILES_PATH / "sounds/music_Koyaanisqatsi.mp3"
    # )
    # music = game.app.loader.loadMusic(DATAFILES_PATH / "sounds/music_westworld.mp3")
    # music.setLoop(True)
    # music.setVolume(0.8)
    # music.play()

    """
    Initialize player and ship
    """
    game.player = Player(
        game=game,
        ship_type="a-wing",
        ini_position=np.array([0, 0, 0]),
        is_neutral=True,
        has_ai=False,
    )

    """
    Build scene
    `asteroids` or `lava_planet` or `debug_collisions`
    """

    game.scene = scene_factory(game=game, scene_name="asteroids")

    """
    Initialize dummy bots
    """

    wp_distance = 1000
    waypoints = [
        np.array([0, 0, 0]),
        np.array([0, wp_distance, 0]),
        np.array([0, wp_distance, wp_distance]),
        np.array([0, 0, wp_distance]),
        np.array([wp_distance, 0, wp_distance]),
        np.array([wp_distance, 0, 0]),
        np.array([0, 0, 0]),
        np.array([0, -wp_distance, 0]),
        np.array([0, -wp_distance, -wp_distance]),
        np.array([0, 0, -wp_distance]),
        np.array([-wp_distance, 0, -wp_distance]),
        np.array([-wp_distance, 0, 0]),
    ]
    game.lead_bot = spawn_bot(
        game=game,
        name="lead_2",
        ship_type="tie-interceptor",
        ini_position=np.array([0, -200, 2]),
        has_debug_trihedron=True,
        team=2,
        debug_decisions=True,
    )
    game.lead_bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)

    game.chase_bot = spawn_bot(
        game=game,
        name="chase_1",
        ship_type="a-wing",
        ini_position=np.array([0, -2000, -0]),
        has_debug_trihedron=True,
        team=1,
        debug_decisions=True,
    )
    game.chase_bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)

    for _ in range(5):
        bot = spawn_bot(
            game=game,
            name="team_1",
            ship_type="x-wing",
            ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
            has_debug_trihedron=True,
            team=1,
        )
        bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)

    for _ in range(5):
        bot = spawn_bot(
            game=game,
            name="team_2",
            ship_type="tie-interceptor",
            ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
            has_debug_trihedron=True,
            team=2,
        )
        bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)
