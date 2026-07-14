# {py:mod}`space_flight.utils.state_machine`

```{py:module} space_flight.utils.state_machine
```

```{autodoc2-docstring} space_flight.utils.state_machine
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`StateMachine <space_flight.utils.state_machine.StateMachine>`
  - ```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine
    :summary:
    ```
* - {py:obj}`Cooldown <space_flight.utils.state_machine.Cooldown>`
  - ```{autodoc2-docstring} space_flight.utils.state_machine.Cooldown
    :summary:
    ```
````

### API

`````{py:class} StateMachine(initial_state: typing.Hashable, clock: typing.Callable[[], float], commit_times: typing.Optional[typing.Union[float, dict]] = None, name: str = '')
:canonical: space_flight.utils.state_machine.StateMachine

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.__init__
```

````{py:property} state
:canonical: space_flight.utils.state_machine.StateMachine.state
:type: typing.Hashable

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.state
```

````

````{py:property} previous_state
:canonical: space_flight.utils.state_machine.StateMachine.previous_state
:type: typing.Optional[typing.Hashable]

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.previous_state
```

````

````{py:property} time_in_state_s
:canonical: space_flight.utils.state_machine.StateMachine.time_in_state_s
:type: float

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.time_in_state_s
```

````

````{py:method} commit_time_s(state: typing.Optional[typing.Hashable] = None) -> float
:canonical: space_flight.utils.state_machine.StateMachine.commit_time_s

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.commit_time_s
```

````

````{py:method} is_committed() -> bool
:canonical: space_flight.utils.state_machine.StateMachine.is_committed

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.is_committed
```

````

````{py:method} on_enter(state: typing.Hashable, callback: typing.Callable[[], None])
:canonical: space_flight.utils.state_machine.StateMachine.on_enter

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.on_enter
```

````

````{py:method} on_exit(state: typing.Hashable, callback: typing.Callable[[], None])
:canonical: space_flight.utils.state_machine.StateMachine.on_exit

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.on_exit
```

````

````{py:method} request(new_state: typing.Hashable, force: bool = False) -> bool
:canonical: space_flight.utils.state_machine.StateMachine.request

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.request
```

````

````{py:method} reset_timer()
:canonical: space_flight.utils.state_machine.StateMachine.reset_timer

```{autodoc2-docstring} space_flight.utils.state_machine.StateMachine.reset_timer
```

````

`````

`````{py:class} Cooldown(duration_s: float, clock: typing.Callable[[], float], ready_at_start: bool = True)
:canonical: space_flight.utils.state_machine.Cooldown

```{autodoc2-docstring} space_flight.utils.state_machine.Cooldown
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.utils.state_machine.Cooldown.__init__
```

````{py:method} trigger()
:canonical: space_flight.utils.state_machine.Cooldown.trigger

```{autodoc2-docstring} space_flight.utils.state_machine.Cooldown.trigger
```

````

````{py:method} elapsed_s() -> float
:canonical: space_flight.utils.state_machine.Cooldown.elapsed_s

```{autodoc2-docstring} space_flight.utils.state_machine.Cooldown.elapsed_s
```

````

````{py:method} ready(multiplier: float = 1.0) -> bool
:canonical: space_flight.utils.state_machine.Cooldown.ready

```{autodoc2-docstring} space_flight.utils.state_machine.Cooldown.ready
```

````

`````
