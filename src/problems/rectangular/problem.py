import logging
import copy

import numpy as num

from pyrocko import gf, util
from pyrocko.guts import String, Float, Dict, StringChoice, Int, clone

from grond.meta import (
    GrondError,
    expand_template,
    Parameter,
    has_get_plot_classes,
    Forbidden,
)

from ..base import Problem, ProblemConfig

guts_prefix = "grond"
logger = logging.getLogger("grond.problems.rectangular.problem")
km = 1e3
as_km = dict(scale_factor=km, scale_unit="km")


class RectangularProblemConfig(ProblemConfig):
    ranges = Dict.T(String.T(), gf.Range.T())
    decimation_factor = Int.T(default=1)
    distance_min = Float.T(default=0.0)
    nthreads = Int.T(default=4)

    def get_problem(self, event_group, target_groups, targets):
        if len(event_group.get_events()) != 1:
            raise GrondError("RectangularProblem cannot handle multi-events.")

        event = copy.deepcopy(event_group.get_events()[0])

        if event.depth is None:
            event.depth = 0

        if self.decimation_factor != 1:
            logger.warn(
                "Decimation factor for rectangular source set to %i. Results "
                "may be inaccurate." % self.decimation_factor
            )

        base_source = gf.RectangularSource.from_pyrocko_event(
            event, anchor="top", decimation_factor=self.decimation_factor
        )

        subs = dict(event_name=event.name, event_time=util.time_to_str(event.time))

        problem = RectangularProblem(
            name=expand_template(self.name_template, subs),
            base_source=base_source,
            distance_min=self.distance_min,
            target_groups=target_groups,
            targets=targets,
            ranges=self.ranges,
            norm_exponent=self.norm_exponent,
            nthreads=self.nthreads,
        )

        return problem


@has_get_plot_classes
class RectangularProblem(Problem):
    # nucleation_x
    # nucleation_y
    # time
    # stf

    problem_parameters = [
        Parameter("east_shift", "m", label="Easting", **as_km),
        Parameter("north_shift", "m", label="Northing", **as_km),
        Parameter("depth", "m", label="Depth", **as_km),
        Parameter("length", "m", label="Length", **as_km),
        Parameter("width", "m", label="Width", **as_km),
        Parameter("slip", "m", label="Slip"),
        Parameter("strike", "deg", label="Strike"),
        Parameter("dip", "deg", label="Dip"),
        Parameter("rake", "deg", label="Rake"),
    ]

    problem_waveform_parameters = [
        Parameter("nucleation_x", "offset", label="Nucleation X"),
        Parameter("nucleation_y", "offset", label="Nucleation Y"),
        Parameter("time", "s", label="Time"),
        Parameter("velocity", "m/s", label="Rupture Velocity"),
    ]

    dependants = []

    distance_min = Float.T(default=0.0)

    def pack(self, source):
        arr = self.get_parameter_array(source)
        for ip, p in enumerate(self.parameters):
            if p.name == "time":
                arr[ip] -= self.base_source.time
        return arr

    def get_source(self, x):
        d = self.get_parameter_dict(x)
        p = {}
        for k in self.base_source.keys():
            if k in d:
                p[k] = float(self.ranges[k].make_relative(self.base_source[k], d[k]))

        source = self.base_source.clone(**p)

        return source

    def random_uniform(self, xbounds, rstate):
        x = num.zeros(self.nparameters)
        for i in range(self.nparameters):
            x[i] = rstate.uniform(xbounds[i, 0], xbounds[i, 1])

        return x

    def preconstrain(self, x):
        # source = self.get_source(x)
        # if any(self.distance_min > source.distance_to(t)
        #        for t in self.targets):
        # raise Forbidden()
        return x

    @classmethod
    def get_plot_classes(cls):
        plots = super(RectangularProblem, cls).get_plot_classes()
        return plots


class MultiRectangularProblemConfig(ProblemConfig):
    ranges = Dict.T(String.T(), Dict.T(String.T(), gf.Range.T()))
    # ranges2 = Dict.T(String.T(), gf.Range.T())
    decimation_factor = Int.T(default=1)
    distance_min = Float.T(default=0.0)
    nthreads = Int.T(default=1)

    def need_event_group(self):
        return True

    def get_problem(self, event_group, target_groups, targets):
        sources = []
        for event in event_group.get_events():
            source = gf.RectangularSource.from_pyrocko_event(
                event, anchor="top", decimation_factor=self.decimation_factor
            )

            sources.append(source)

        base_source = gf.CombiSource(name=event_group.name, subsources=sources)

        subs = dict(event_name=event_group.name)

        ranges_all = {}
        for k in self.ranges.keys():
            for i in self.ranges[k]:
                if k == "default":
                    ranges_all[i] = self.ranges[k][i]
                elif k in event_group.event_names:
                    ranges_all[k + "." + i] = self.ranges[k][i]
                else:
                    pass

        problem = MultiRectangularProblem(
            name=expand_template(self.name_template, subs),
            base_source=base_source,
            target_groups=target_groups,
            targets=targets,
            ranges=ranges_all,
            distance_min=self.distance_min,
            norm_exponent=self.norm_exponent,
            nthreads=self.nthreads,
        )

        return problem


@has_get_plot_classes
class MultiRectangularProblem(Problem):
    problem_parameters_single = [
        Parameter("east_shift", "m", label="Easting", **as_km),
        Parameter("north_shift", "m", label="Northing", **as_km),
        Parameter("depth", "m", label="Depth", **as_km),
        Parameter("length", "m", label="Length", **as_km),
        Parameter("width", "m", label="Width", **as_km),
        Parameter("slip", "m", label="Slip"),
        Parameter("strike", "deg", label="Strike"),
        Parameter("dip", "deg", label="Dip"),
        Parameter("rake", "deg", label="Rake"),
    ]

    problem_waveform_parameters_single = [
        Parameter("nucleation_x", "offset", label="Nucleation X"),
        Parameter("nucleation_y", "offset", label="Nucleation Y"),
        Parameter("time", "s", label="Time"),
        Parameter("velocity", "m/s", label="Rupture Velocity"),
    ]

    dependants_single = []

    distance_min = Float.T(default=0.0)

    def __init__(self, **kwargs):
        Problem.__init__(self, **kwargs)
        self.deps_cache = {}

        parameters = []
        dependants = []
        for source in self.base_source.subsources:
            for bparameter in (
                self.problem_parameters_single + self.problem_waveform_parameters_single
            ):
                parameter = clone(bparameter)
                parameter.name = ".".join([source.name, bparameter.name])
                parameters.append(parameter)

        self.nsubsources = len(self.base_source.subsources)

        self.problem_parameters = parameters
        self.dependants = dependants

    def get_range(self, k):
        try:
            return self.ranges[k]
        except KeyError:
            return self.ranges[k.split(".")[1]]
        except (IndexError, KeyError):
            raise GrondError("Invalid range key: %s" % k)

    def get_source(self, x):
        d = self.get_parameter_dict(x)
        subsources = []
        for source in self.base_source.subsources:
            n = source.name
            p = {}
            for k in source.keys():
                if n + "." + k in d:
                    p[k] = float(
                        self.get_range("." + k).make_relative(source[k], d[n + "." + k])
                    )

            csource = source.clone(**p)
            subsources.append(csource)
        source = self.base_source.clone(subsources=subsources)
        return source

    def pack(self, source):
        xs = []
        for isub, subsource in enumerate(source.subsources):
            if hasattr(self, "problem_waveform_parameters_single"):
                xs.append(
                    num.array(
                        [
                            subsource.north_shift,
                            subsource.east_shift,
                            subsource.depth,
                            subsource.length,
                            subsource.width,
                            subsource.slip,
                            subsource.strike,
                            subsource.dip,
                            subsource.rake,
                            subsource.nucleation_x,
                            subsource.nucleation_y,
                            subsource.time - self.base_source.subsources[isub].time,
                        ]
                    )
                )
            else:
                xs.append(
                    num.array(
                        [
                            subsource.north_shift,
                            subsource.east_shift,
                            subsource.depth,
                            subsource.length,
                            subsource.width,
                            subsource.slip,
                            subsource.strike,
                            subsource.dip,
                            subsource.rake,
                        ]
                    )
                )
        x = num.concatenate(xs)
        return x

    def random_uniform(self, xbounds, rstate):
        x = num.zeros(self.nparameters)
        for i in range(self.nparameters):
            x[i] = rstate.uniform(xbounds[i, 0], xbounds[i, 1])

        return x

    def preconstrain(self, x):
        def check_rectangles_intersect(sources):
            surfaces = []
            for i, source in enumerate(sources):
                points = source.outline()
                X, Y, Z = points[:, 0], points[:, 1], points[:, 2]
                points_lonlat = source.outline(cs="lonlat")
                LO, LA = points_lonlat[:, 0], points_lonlat[:, 1]
                surfaces.append([list(zip(LO, LA, Z))])
            rect1 = surfaces[0][0]
            rect2 = surfaces[1][0]

            # Compute the normal vectors to the faces of each rectangle
            rect1_normals = get_normals(rect1)
            rect2_normals = get_normals(rect2)

            # Compute the projections of the rectangles onto each axis defined by their normals
            for normal in rect1_normals + rect2_normals:
                min1, max1 = project_onto_axis(normal, rect1)
                min2, max2 = project_onto_axis(normal, rect2)
                if not overlap(min1, max1, min2, max2):
                    return False

            return True

        def get_normals(rect):
            # Compute the normal vectors to the faces of the rectangle
            normals = []
            for i in range(4):
                v1 = num.array(rect[(i + 1) % 4]) - num.array(rect[i])
                v2 = num.array(rect[(i + 2) % 4]) - num.array(rect[i])
                normals.append(num.cross(v1, v2))
            return normals

        def project_onto_axis(axis, points):
            # Project the points onto the axis and return the minimum and maximum values
            min_proj = num.dot(axis, points[0])
            max_proj = min_proj
            for i in range(1, 4):
                proj = num.dot(axis, points[i])
                if proj < min_proj:
                    min_proj = proj
                elif proj > max_proj:
                    max_proj = proj
            return min_proj, max_proj

        def overlap(min1, max1, min2, max2):
            # Check if the intervals [min1, max1] and [min2, max2] overlap
            return max(min1, min2) <= min(max1, max2)

        for i, source in enumerate(self.get_source(x).subsources):
            for source2 in self.base_source.subsources[i + 1 :]:
                if check_rectangles_intersect([source, source2]):
                    logger.warning("Falsch")
                    raise Forbidden()
                else:
                    # logger.warning("top")
                    pass
        return x

    @classmethod
    def get_plot_classes(cls):
        from .. import plot  # noqa

        plots = super(MultiRectangularProblem, cls).get_plot_classes()
        return plots


__all__ = """
    RectangularProblem
    RectangularProblemConfig
    MultiRectangularProblem
    MultiRectangularProblemConfig
""".split()
