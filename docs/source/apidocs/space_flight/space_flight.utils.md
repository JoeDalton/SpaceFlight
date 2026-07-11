# {py:mod}`space_flight.utils`

```{py:module} space_flight.utils
```

```{autodoc2-docstring} space_flight.utils
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`rotate_single_vector <space_flight.utils.rotate_single_vector>`
  - ```{autodoc2-docstring} space_flight.utils.rotate_single_vector
    :summary:
    ```
* - {py:obj}`safe_angle_rad <space_flight.utils.safe_angle_rad>`
  - ```{autodoc2-docstring} space_flight.utils.safe_angle_rad
    :summary:
    ```
* - {py:obj}`low_pass_filter_first_order <space_flight.utils.low_pass_filter_first_order>`
  - ```{autodoc2-docstring} space_flight.utils.low_pass_filter_first_order
    :summary:
    ```
* - {py:obj}`smooth_step_down <space_flight.utils.smooth_step_down>`
  - ```{autodoc2-docstring} space_flight.utils.smooth_step_down
    :summary:
    ```
* - {py:obj}`smooth_step_up <space_flight.utils.smooth_step_up>`
  - ```{autodoc2-docstring} space_flight.utils.smooth_step_up
    :summary:
    ```
* - {py:obj}`sample_unit_sphere <space_flight.utils.sample_unit_sphere>`
  - ```{autodoc2-docstring} space_flight.utils.sample_unit_sphere
    :summary:
    ```
* - {py:obj}`build_orthogonal_basis <space_flight.utils.build_orthogonal_basis>`
  - ```{autodoc2-docstring} space_flight.utils.build_orthogonal_basis
    :summary:
    ```
* - {py:obj}`sample_direction_in_cone <space_flight.utils.sample_direction_in_cone>`
  - ```{autodoc2-docstring} space_flight.utils.sample_direction_in_cone
    :summary:
    ```
* - {py:obj}`build_axis_billboard_quat <space_flight.utils.build_axis_billboard_quat>`
  - ```{autodoc2-docstring} space_flight.utils.build_axis_billboard_quat
    :summary:
    ```
* - {py:obj}`compute_next_power_of_2 <space_flight.utils.compute_next_power_of_2>`
  - ```{autodoc2-docstring} space_flight.utils.compute_next_power_of_2
    :summary:
    ```
````

### API

````{py:function} rotate_single_vector(quat: numpy.quaternion, vector: numpy.ndarray)
:canonical: space_flight.utils.rotate_single_vector

```{autodoc2-docstring} space_flight.utils.rotate_single_vector
```
````

````{py:function} safe_angle_rad(angle_rad: float) -> float
:canonical: space_flight.utils.safe_angle_rad

```{autodoc2-docstring} space_flight.utils.safe_angle_rad
```
````

````{py:function} low_pass_filter_first_order(value: typing.Union[float, numpy.ndarray], previous: typing.Union[float, numpy.ndarray], dt: float, rise_time: float, fall_time: float) -> typing.Union[float, numpy.ndarray]
:canonical: space_flight.utils.low_pass_filter_first_order

```{autodoc2-docstring} space_flight.utils.low_pass_filter_first_order
```
````

````{py:function} smooth_step_down(x: typing.Union[float, numpy.ndarray], x_step: float, slope: float) -> typing.Union[float, numpy.ndarray]
:canonical: space_flight.utils.smooth_step_down

```{autodoc2-docstring} space_flight.utils.smooth_step_down
```
````

````{py:function} smooth_step_up(x: typing.Union[float, numpy.ndarray], x_step: float, slope: float) -> typing.Union[float, numpy.ndarray]
:canonical: space_flight.utils.smooth_step_up

```{autodoc2-docstring} space_flight.utils.smooth_step_up
```
````

````{py:function} sample_unit_sphere() -> numpy.ndarray
:canonical: space_flight.utils.sample_unit_sphere

```{autodoc2-docstring} space_flight.utils.sample_unit_sphere
```
````

````{py:function} build_orthogonal_basis(normal: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]
:canonical: space_flight.utils.build_orthogonal_basis

```{autodoc2-docstring} space_flight.utils.build_orthogonal_basis
```
````

````{py:function} sample_direction_in_cone(normal: numpy.ndarray, tangent: numpy.ndarray, bitangent: numpy.ndarray, half_angle_rad: float) -> numpy.ndarray
:canonical: space_flight.utils.sample_direction_in_cone

```{autodoc2-docstring} space_flight.utils.sample_direction_in_cone
```
````

````{py:function} build_axis_billboard_quat(forward: numpy.ndarray, up_hint: numpy.ndarray = None) -> quaternion
:canonical: space_flight.utils.build_axis_billboard_quat

```{autodoc2-docstring} space_flight.utils.build_axis_billboard_quat
```
````

````{py:function} compute_next_power_of_2(x: float) -> float
:canonical: space_flight.utils.compute_next_power_of_2

```{autodoc2-docstring} space_flight.utils.compute_next_power_of_2
```
````
