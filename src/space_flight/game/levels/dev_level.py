import numpy as np

from space_flight.actors.bot import spawn_bot
from space_flight.actors.player import Player
from space_flight.ai.formation import Formation
from space_flight.scenes.scenes import scene_factory


def build_dev_level(game):
    """
    A function to build a development level
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
        ini_position=np.array([100, -800, 505]),
        is_neutral=True,
        has_ai=False,
    )

    """
    Build scene
    `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    """

    game.scene = scene_factory(game=game, scene_name="ocean_planet")

    """
    Initialize dummy bots
    """

    game.team_2_formation = Formation(scale_m=100, shape="around_diamond")

    wp_distance = 5000
    waypoints = [
        np.array([0, 100, 500]),
    ]
    # Make a circle
    n_waypoint = 5
    for angle_reduced in range(n_waypoint):
        angle = angle_reduced * 2 * np.pi / n_waypoint
        waypoints.append(
            np.array([wp_distance * np.sin(angle), wp_distance * np.cos(angle), 500])
        )

    game.lead_bot = spawn_bot(
        game=game,
        name="lead_2",
        bot_type="capital_ship",
        pawn_model="cr-90",
        ini_position=np.array([0, 0, 500]),
        team=2,
        debug_decisions=False,
    )
    game.lead_bot.navigator.set_waypoints(waypoints=waypoints, is_loop=True)
    game.team_2_formation.add_ship(ship=game.lead_bot.pawn)

    game.turret_1 = spawn_bot(
        game=game,
        name="turret_1",
        bot_type="turret",
        pawn_model="test",
        base_position=np.array([100, -5600, 400]),
        team=1,
        debug_decisions=False,
    )

    game.turret_2 = spawn_bot(
        game=game,
        name="turret_2",
        bot_type="turret",
        pawn_model="test",
        base_position=np.array([-100, -5600, 400]),
        team=1,
        debug_decisions=False,
    )

    # Define level scenario
    game.scenario_events["bots_spawned"] = False

    game.update_scenario_method = update_scenario_method


def update_scenario_method(game):
    """
    Updates the scenario
    """

    if (game.game_time.get_current_time() > 1) and (
        not game.scenario_events["bots_spawned"]
    ):
        game.scenario_events["bots_spawned"] = True
        n_follower = 8
        for i in range(n_follower):
            bot = spawn_bot(
                game=game,
                name="team_2, ",
                bot_type="fighter",
                pawn_model="y-wing",
                ini_position=np.array([-(int(n_follower / 2)) + 50 * i, -700, 500]),
                team=2,
                debug_decisions=False,
            )
            game.team_2_formation.add_ship(ship=bot.pawn)
            # bot.tactician.primary_target_ids.append(game.turret_2.pawn.id)

    return
