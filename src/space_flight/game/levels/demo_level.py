import numpy as np

from space_flight.ai import Formation
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
        ini_position=np.array([0, -1000, 0]),
        is_neutral=True,
        has_ai=False,
    )

    """
    Build scene
    `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    """

    game.scene = scene_factory(game=game, scene_name="debug")

    """
    Initialize dummy bots
    """

    team_2_formation = Formation()

    wp_distance = 10000
    waypoints = [
        np.array([0, 0, 0]),
        np.array([0, wp_distance, 0]),
        # np.array([0, wp_distance, wp_distance]),
        # np.array([0, 0, wp_distance]),
        # np.array([wp_distance, 0, wp_distance]),
        # np.array([wp_distance, 0, 0]),
        # np.array([0, 0, 0]),
        # np.array([0, -wp_distance, 0]),
        # np.array([0, -wp_distance, -wp_distance]),
        # np.array([0, 0, -wp_distance]),
        # np.array([-wp_distance, 0, -wp_distance]),
        # np.array([-wp_distance, 0, 0]),
    ]
    game.lead_bot = spawn_bot(
        game=game,
        name="lead_2",
        ship_type="tie-interceptor",
        ini_position=np.array([0, -100, 0]),
        has_debug_trihedron=False,
        team=2,
        debug_decisions=False,
    )
    game.lead_bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)
    team_2_formation.add_ship(ship=game.lead_bot.ship)

    # game.follow_bot = spawn_bot(
    #     game=game,
    #     name="follow_2",
    #     ship_type="tie-interceptor",
    #     ini_position=np.array([0, -300, 0]),
    #     has_debug_trihedron=False,
    #     team=2,
    # )
    # team_2_formation.add_ship(ship=game.follow_bot.ship)

    # for _ in range(0):
    #     bot = spawn_bot(
    #         game=game,
    #         name="team_2",
    #         ship_type="tie-interceptor",
    #         ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
    #         has_debug_trihedron=False,
    #         team=2,
    #     )
    #     team_2_formation.add_ship(ship=bot.ship)

    # chase_bot = spawn_bot(
    #     game=game,
    #     name="chase_1",
    #     ship_type="a-wing",
    #     ini_position=np.array([0, -2000, -0]),
    #     has_debug_trihedron=False,
    #     team=1,
    #     debug_decisions=False,
    # )
    # chase_bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)

    # for _ in range(5):
    #     bot = spawn_bot(
    #         game=game,
    #         name="team_1",
    #         ship_type="x-wing",
    #         ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
    #         has_debug_trihedron=False,
    #         team=1,
    #     )
    #     bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)
