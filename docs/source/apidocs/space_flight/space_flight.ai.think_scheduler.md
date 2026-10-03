# {py:mod}`space_flight.ai.think_scheduler`

```{py:module} space_flight.ai.think_scheduler
```

```{autodoc2-docstring} space_flight.ai.think_scheduler
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ThinkSlot <space_flight.ai.think_scheduler.ThinkSlot>`
  - ```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkSlot
    :summary:
    ```
* - {py:obj}`ThinkScheduler <space_flight.ai.think_scheduler.ThinkScheduler>`
  - ```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkScheduler
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`THINK_SLOT_S <space_flight.ai.think_scheduler.THINK_SLOT_S>`
  - ```{autodoc2-docstring} space_flight.ai.think_scheduler.THINK_SLOT_S
    :summary:
    ```
````

### API

````{py:data} THINK_SLOT_S
:canonical: space_flight.ai.think_scheduler.THINK_SLOT_S
:value: >
   None

```{autodoc2-docstring} space_flight.ai.think_scheduler.THINK_SLOT_S
```

````

`````{py:class} ThinkSlot(scheduler: space_flight.ai.think_scheduler.ThinkScheduler, phase: int, n_slots: int)
:canonical: space_flight.ai.think_scheduler.ThinkSlot

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkSlot
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkSlot.__init__
```

````{py:property} period_s
:canonical: space_flight.ai.think_scheduler.ThinkSlot.period_s
:type: float

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkSlot.period_s
```

````

````{py:method} next_due_time_s(now_s: float) -> float
:canonical: space_flight.ai.think_scheduler.ThinkSlot.next_due_time_s

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkSlot.next_due_time_s
```

````

`````

`````{py:class} ThinkScheduler(slot_s: float = THINK_SLOT_S)
:canonical: space_flight.ai.think_scheduler.ThinkScheduler

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkScheduler
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkScheduler.__init__
```

````{py:method} register(period_s: float) -> space_flight.ai.think_scheduler.ThinkSlot
:canonical: space_flight.ai.think_scheduler.ThinkScheduler.register

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkScheduler.register
```

````

````{py:method} unregister(slot: space_flight.ai.think_scheduler.ThinkSlot)
:canonical: space_flight.ai.think_scheduler.ThinkScheduler.unregister

```{autodoc2-docstring} space_flight.ai.think_scheduler.ThinkScheduler.unregister
```

````

`````
