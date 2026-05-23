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
        ini_position=np.array([0, -2600, 250]),
        is_neutral=False,
        has_ai=False,
    )

    """
    Build scene
    `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    """

    game.scene = scene_factory(game=game, scene_name="ocean_planet")

    """
    Initialize allies
    """
    # Initialize convoy formation
    game.team_1_formation = Formation(scale_m=150)

    # Define transport waypoints
    transport_waypoints = [
        np.array([0, 0, 200]),
        np.array([0, 3000, 200]),
        np.array([500, 4000, 200]),
        np.array([1000, 4500, 200]),
        np.array([2000, 5000, 200]),
        np.array([5000, 5000, 200]),
        np.array([6000, 4500, 200]),
        np.array([6500, 4000, 200]),
        np.array([7000, 3000, 200]),
    ]

    # Spawn transports
    game.transport_bots = []
    n_transports = 3
    for i in range(n_transports):
        if i == 0:
            r_pos = np.zeros(3)
        elif i == 1:
            r_pos = np.array([-150, -150, 75])
        elif i == 2:
            r_pos = np.array([150, -150, 75])
        bot = spawn_bot(
            game=game,
            name=f"transport_{i+1}",
            bot_type="capital_ship",
            pawn_model="gr-75",
            ini_position=np.array([0, -2000, 200]) + r_pos,
            team=1,
            debug_decisions=False,
        )
        # All transport ships get the waypoints in case the leader is destroyed
        bot.navigator.set_waypoints(waypoints=transport_waypoints, is_loop=True)
        game.transport_bots.append(bot)
        game.team_1_formation.add_ship(ship=bot.pawn)

    # Spawn escort
    n_follower = 8
    for i in range(n_follower):
        bot = spawn_bot(
            game=game,
            name=f"escort_ship_{i}",
            bot_type="fighter",
            pawn_model="x-wing",
            ini_position=np.array([(int(n_follower / 2)) * 100 - 100 * i, -2500, 300]),
            team=1,
            debug_decisions=False,
        )
        game.team_1_formation.add_ship(ship=bot.pawn)

    # Set custom formation positions
    game.team_1_formation.relative_positions = [
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, -1.0, 0.5]),
        np.array([-1.0, -1.0, 0.5]),
        np.array([1.4, 2.0, 0.0]),
        np.array([-1.4, 2.0, 0.0]),
        np.array([0.0, 2.0, -1.0]),
        np.array([0.0, -2.0, 1.0]),
        np.array([0.0, -2.0, 0.0]),
        np.array([1.0, -2.0, 0.0]),
        np.array([-1.0, -2.0, 0.0]),
        np.array([0.0, -3.0, 0.0]),
    ]

    """
    Initialize scenario
    """
    # Define level scenario
    game.team_2_formation1 = Formation(scale_m=30, shape="arrowhead")
    game.team_2_formation2 = Formation(scale_m=30, shape="diamond")
    game.team_2_formation3 = Formation(scale_m=30, shape="around_diamond")
    game.scenario_data = {
        "first_wave": {
            "spawned": False,
            "size": 5,
            "ship_model": "tie-bomber",
            "spawn_point": np.array([300, 6000, 500]),
            "spawn_orientation": np.array([0, 0, 0, 1]),
            "spawn_time_s": 40,
            "waypoints": [
                np.array([300, 0, 500]),
                np.array([300, -6000, 500]),
            ],
        },
        "second_wave": {
            "spawned": False,
            "size": 5,
            "ship_model": "tie-interceptor",
            "spawn_point": np.array([300, 6300, 800]),
            "spawn_orientation": np.array([0, 0, 0, 1]),
            "spawn_time_s": 45,
            "waypoints": [
                np.array([300, 0, 500]),
                np.array([300, -6000, 500]),
            ],
        },
        "third_wave": {
            "spawned": False,
            "size": 8,
            "ship_model": "tie-interceptor",
            "spawn_point": np.array([300, 0, 800]),
            "spawn_orientation": np.array([0, 0, 0, 1]),
            "spawn_time_s": 200,
            "waypoints": [
                np.array([300, 6000, 500]),
                np.array([300, 0, 500]),
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
                    if "first" in key:
                        game.team_2_formation1.add_ship(ship=bot.pawn)
                    elif "second" in key:
                        game.team_2_formation2.add_ship(ship=bot.pawn)
                    elif "third" in key:
                        game.team_2_formation3.add_ship(ship=bot.pawn)
                    # Set patrol waypoints
                    bot.navigator.set_waypoints(
                        waypoints=value["waypoints"], is_loop=True
                    )
                    # Set transports as primary targets
                    for transport in game.transport_bots:
                        try:
                            bot.tactician.primary_target_ids.append(transport.pawn.id)
                        except AttributeError:
                            pass
                # Warn player
                game.hud.set_event_text(
                    text="Enemy ships incoming!", display_time_s=2.5
                )

    return
