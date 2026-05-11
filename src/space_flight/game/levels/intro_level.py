import numpy as np

from space_flight.actors.bot import spawn_bot
from space_flight.actors.player import Player
from space_flight.ai.formation import Formation
from space_flight.scenes.scenes import scene_factory


def build_intro_level(game):
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
        ini_position=np.array([0, -2500, 100]),
        is_neutral=False,
        has_ai=False,
    )

    """
    Build scene
    `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    """

    game.scene = scene_factory(game=game, scene_name="lava_planet")

    """
    Initialize allies
    """
    # Initialize convoy formation
    game.team_1_formation = Formation(scale_m=100, shape="diamond")

    # Define transport waypoints
    transport_waypoints = [
        np.array([0, 0, 0]),
        np.array([0, 3000, 0]),
    ]

    # Spawn transports
    game.transport_bots = []
    n_transports = 3
    for i in range(n_transports):
        bot = spawn_bot(
            game=game,
            name=f"transport_{i+1}",
            bot_type="capital_ship",
            pawn_model="gr-75",
            ini_position=np.array(
                [-(int(n_transports / 2)) * 100 + 100 * i, -2000 - i * 100, 0]
            ),
            team=1,
            debug_decisions=False,
        )
        # All transport ships get the waypoints in case the leader is destroyed
        bot.navigator.set_waypoints(waypoints=transport_waypoints, is_loop=False)
        game.transport_bots.append(bot)
        game.team_1_formation.add_ship(ship=bot.pawn)

    # Spawn escort
    n_follower = 3
    for i in range(n_follower):
        bot = spawn_bot(
            game=game,
            name=f"escort_ship_{i}",
            bot_type="fighter",
            pawn_model="x-wing",
            ini_position=np.array([-(int(n_follower / 2)) * 100 + 100 * i, -2300, 0]),
            team=1,
            debug_decisions=False,
        )
        game.team_1_formation.add_ship(ship=bot.pawn)

    """
    Initialize scenario
    """
    # Define level scenario
    game.team_2_formation = Formation(scale_m=30, shape="arrowhead")
    game.scenario_data = {
        "first_wave": {
            "spawned": False,
            "size": 3,
            "ship_model": "tie-bomber",
            "spawn_point": np.array([300, 3000, -300]),
            "spaw_orientation": np.array([0, 0, 0, 1]),
            "spawn_time_s": 30,
            "waypoints": [
                np.array([300, 0, -300]),
                np.array([300, -3000, -300]),
            ],
        },
        "second_wave": {
            "spawned": False,
            "size": 3,
            "ship_model": "tie-interceptor",
            "spawn_point": np.array([300, 3000, -300]),
            "spaw_orientation": np.array([0, 0, 0, 1]),
            "spawn_time_s": 120,
            "waypoints": [
                np.array([300, 0, -300]),
                np.array([300, -3000, -300]),
            ],
        },
    }
    game.update_scenario_method = update_scenario_method


def update_scenario_method(game):
    """
    Makes the scenario progress over time
    """
    current_time_s = game.game_time.get_current_time()
    for key, value in game.scenario_data.items():
        if "wave" in key:
            if (not value["spawned"]) and (current_time_s > value["spawn_time_s"]):
                # Spawn wave
                value["spawned"] = True

                for i in range(value["size"]):
                    bot = spawn_bot(
                        game=game,
                        name=f"aggressor_{i}",
                        bot_type="fighter",
                        pawn_model=value["ship_model"],
                        ini_position=value["spawn_point"]
                        + np.array([-(int(value["size"] / 2)) * 50 + 50 * i, 0, 0]),
                        ini_orientation=value["spawn_orientation"],
                        team=2,
                        debug_decisions=False,
                    )
                    game.team_2_formation.add_ship(ship=bot.pawn)
                    # Set transports as primary targets
                    for transport in game.transport_bots:
                        bot.tactician.primary_target_ids.append(transport.pawn.id)

    return
