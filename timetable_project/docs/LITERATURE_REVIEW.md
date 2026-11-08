# Focused literature review: university course timetabling

**Review date:** 17 October 2026  
**Purpose:** Select an implementable first scheduling engine for this repository,
not establish a universally best timetabling algorithm.

## Objective and questions

This focused, narrative review asks which algorithm family best fits an
institution-facing tool that must express required and preferred rules, return
an inspectable assignment, expose a reliable stopping status, and validate a
schedule independently. It compares constraint programming / CSP, integer
optimization and CP-SAT, genetic algorithms, simulated annealing, tabu search,
and hybrid or hyper-heuristic methods.

## Search strategy and selection

Sources were checked on 17 October 2026 using Crossref DOI metadata, OpenAlex
work and author metadata, the official ITC 2019 format/DTD, and the OR-Tools
CP-SAT guide. Search terms included *university course timetabling*, *UCTP*,
*ITC 2019*, *constraint programming*, *MIP*, *CP-SAT*, *MaxSAT*, *genetic
algorithm*, *simulated annealing*, *tabu search*, and *hyper-heuristic*.
Priority went to peer-reviewed review papers, the ITC-2019 benchmark paper,
and papers with verified DOI records; foundational sources were retained to
explain algorithm families. Included papers concern university/educational
timetabling or benchmark methodology. Work on examination timetabling, school
timetabling, and unrelated resource scheduling is not used as direct empirical
evidence for this course-timetabling instance.

This is a bounded, evidence-led review, not a systematic review: full-text
access was not consistently available, there was no double screening, and the
table synthesizes reported scope and general method properties rather than
reproducing numerical comparisons. Metadata was cross-checked against DOI
registries/catalog records where noted. No figures from incompatible benchmark
tracks are compared as if they measured the same problem.

## Evidence and comparison

| Family | Hard-constraint satisfaction | Soft objectives and runtime | Flexibility, explainability, and engineering fit |
|---|---|---|---|
| CSP / constraint programming | Hard requirements are explicit predicates/propagators; a completed solution can be checked exactly. Search may still time out without finding a solution or proving infeasibility. | Feasibility is natural; optimization needs branch-and-bound or an objective layer. Search can degrade when domains and propagation are large. | Rules can be inspectable, but a general efficient propagator for each new rule is costly. Closest to the existing code and useful as an auditable baseline. |
| Integer optimization / CP-SAT / SAT-MaxSAT | Hard requirements can be encoded as constraints; solver statuses distinguish feasible, optimal, infeasible, invalid, and unknown. Correctness depends on a complete encoding. | Weighted preferences fit an objective. Anytime feasible incumbents are possible; time-limited optimality is not guaranteed. A placement-variable formulation can grow with the number of options and pair conflicts. | Strong fit for explicit validation and rule-level explanations when the encoding is tested. The ITC-specific MIP and MaxSAT literature demonstrates problem-specific formulations, not a turnkey model for this codebase (Holm et al., 2022; Lemos et al., 2022). |
| Genetic algorithms | Commonly maintain feasibility through specialized representations/repair, or penalize violations. A penalty alone does not establish feasibility. | Population search can explore broadly; quality and runtime depend on representation, operators, parameters, and instance. Must report feasibility separately from fitness. | Useful where local rules and repair operators are available; validity and reproducibility require careful implementation. The reviewed UCTP literature contains many bespoke variants (Abdipoor et al., 2023; Chen et al., 2021). |
| Simulated annealing | Usually operates on a state and neighborhood; infeasible states may be tolerated with penalties unless moves preserve feasibility. | Can improve an incumbent and has a straightforward time-bounded loop. Cooling schedules, neighborhood structure, and penalty weights materially affect behavior. | Simple runtime control, but a hard-valid initial solution or an explicit violation model is needed for an administration-facing product. Recent UCTP work exists, but its numerical results are tied to its own instance/constraint definition (Sylejmani et al., 2023). |
| Tabu search | Feasibility is not automatic; implementations commonly use feasible neighborhoods or evaluate hard violations separately. | Memory-based local search can avoid cycling and intensify search, but performance depends on neighborhoods, tenure, aspiration, and repair. | Can be effective in a domain-specific solver, but those search choices complicate explanations and robust support for custom requirements. Hybrid approaches are also represented in UCTP research (Abdullah et al., 2012; Lewis, 2008). |
| Hybrid / hyper-heuristic | Inherits feasibility behavior from its low-level heuristics; the controller does not itself prove correctness. | Can combine constructive search, local improvement, and learned heuristic selection; adds tuning and reproducibility concerns. | Attractive later if a single engine struggles, but increases the initial maintenance and testing surface. General hyper-heuristic reviews describe a framework family rather than a transferable performance guarantee (Drake et al., 2020). |

### Interpretation and limitations

The survey by Chen et al. (2021) and the review by Abdipoor et al. (2023)
catalogue diverse UCTP formulations and metaheuristics. Ceschia et al. (2023)
emphasize that educational-timetabling problem definitions and benchmarks
must be distinguished. Müller et al. (2025) describe ITC 2019 as a
real-world university benchmark combining student sectioning with time and
room assignment; that is materially richer than this repository's current
class-placement-only model. Holm et al. (2022) and Lemos et al. (2022) show
that MIP and MaxSAT approaches have been designed for the ITC setting, but
their formulations/results do not prove that this repository's current
CP-SAT adapter supports all ITC rules.

The current local `pu-d5-spr17` parser reports 1,061 classes, 84 rooms, 212
courses, 222 configurations, 13,497 students, and 1,535 distributions (1,262
required, 273 soft). Required rules include 768 `SameAttendees`, 152
`SameDays`, 84 `Precedence`, 115 `WorkDay`, 49 `DifferentDays`, 36 `NotOverlap`,
28 `SameRoom`, 15 `MaxBreaks(0,72)`, 9 `MinGap(6)`, 4 `SameTime`, and 2
`SameStart`. The 15 `MaxBreaks` groups have 14 two-class and one three-class
membership.

`MaxBreaks(R,S)` was checked against the [ITC 2019 format/DTD](https://www.itc2019.org/competition-format.dtd)
and the competition solver implementation ([loader](https://github.com/tomas-muller/cpsolver-itc2019/blob/d1576ac94a8f7b6562e49f9476a89fb741cb226f/src/org/cpsolver/coursett/itc2019/ItcCompetitionLoader.java),
[MaxBreaks constraint](https://github.com/tomas-muller/cpsolver-itc2019/blob/d1576ac94a8f7b6562e49f9476a89fb741cb226f/src/org/cpsolver/coursett/itc2019/ItcMaxBreaksConstraint.java),
[block merging](https://github.com/UniTime/cpsolver/blob/956649b757f49b95a63bb2923fb670c1454bd445/src/org/cpsolver/coursett/constraint/MaxBreaksFlexibleConstraint.java)).
The DTD establishes the input
structure but not the rule semantics. The implementation defines up to `R+1`
blocks per day/week, merging meetings when their free gap is at most `S` time
slots. CP-SAT now handles multi-class groups using per-slot occupancy and
break-count constraints; the independent validator separately merges sorted
meeting intervals. Tests cover an intervening class bridging a gap, exactly
`S` free slots, `S+1` slots, and the allowed number of breaks.

The XML contains 13,497 student requests over 19,614 student-course links,
with course configurations, subparts, classes, parent links, 1,061 class
limits, and 84 room capacities. It has no preassigned class/student
memberships. The request and hierarchy data are sufficient to choose sections:
the pinned competition loader adds each requested course as an offering and,
when no solution memberships are supplied, calls `initialSectioning` across
the course's configuration alternatives. Actual class enrollments are then
derived from those section choices, not from the class `limit` (which is an
upper bound). The source uses student-objective weight 8.

The new CP-SAT sectioning component can optimize and independently validate
student sections and resulting capacity for a fixed complete timetable. Its
current score is a scoped student-conflict-pair count times the student
weight, not the official total score. It does not account for the reference
loader's configurable hard/soft student-conflict split, and the timetable
adapters still return `unsupported` for a nonzero student objective rather
than treating fixed-timetable sectioning as a joint optimum. The latest
10-second full-instance benchmark is therefore non-comparable and does not
establish infeasibility.

The XML distribution inventory is fully recognized by the current hard-rule
CP-SAT and independent-validator implementations, subject to model build
limits. All observed soft distribution types are supported as pairwise
penalties, and tests compare solver objective values to the independent
validator. This does not yet provide joint student-sectioning optimization or official
full-instance objective/validation coverage. `MaxBlock` and soft global
distributions are not in this input and remain unsupported in CP-SAT.

## Research gap and platform implications

The gap for this project is engineering evidence under a single, explicit
normalized instance model—not another unsupported claim that one family
dominates all others. The importer, rule catalog, solver model, and independent
validator need aligned support declarations. Hard-rule omissions must stop a
run; result statuses must distinguish timeout, cancellation, unsupported
model, partial incumbent, and proof of infeasibility. Comparison dashboards
should show only comparable runs and keep dataset, weights, limits, and
versions.

## Algorithm recommendation

Select **OR-Tools CP-SAT** as the first production engine for the platform's
initial supported feature set. This is a scoped implementation choice, not a
claim of universal superiority or a conclusion from the non-comparable
10-second ITC trial. Its integer model can express finite placement choices,
room conflicts, and explicitly tested required rules; its documented statuses
make unknown/timeout distinct from proven infeasibility; and weighted
placement penalties offer a transparent first preference objective. Those
properties suit server-side validation, supportable configuration, and
human-readable reports better than starting with a bespoke evolutionary
search.

This choice is conditional: the adapter implements the required distribution
types observed in `pu-d5-spr17` and its observed soft pairwise objective terms,
but does not yet optimize student sectioning jointly with placement. The
source supplies requests and capacity bounds; section membership and actual
enrollment must be derived by a validated assignment. Before calling CP-SAT a
supported ITC engine, joint student-sectioning semantics, the official total
objective and conflict weighting, and complete independent validation must be
implemented and cross-checked. A
feasibility-preserving local-search hybrid is the next comparison candidate if
measured CP-SAT model size or time-to-first-feasible becomes unacceptable.
Published scores on different instances and objective definitions cannot make
that decision for us.

## References (APA 7)

Abdipoor, S., Yaakob, R., Goh, S. L., & Abdullah, S. (2023). Meta-heuristic
approaches for the University Course Timetabling Problem. *Intelligent Systems
with Applications, 19*, Article 200253.
https://doi.org/10.1016/j.iswa.2023.200253

Abdullah, S., Turabieh, H., McCollum, B., & McMullan, P. (2012). A hybrid
metaheuristic approach to the university course timetabling problem. *Journal
of Heuristics, 18*(1), 1–23. https://doi.org/10.1007/s10732-010-9154-y

Asín Achá, R., & Nieuwenhuis, R. (2014). Curriculum-based course timetabling
with SAT and MaxSAT. *Annals of Operations Research, 218*(1), 71–91.
https://doi.org/10.1007/s10479-012-1081-x

Ceschia, S., Di Gaspero, L., & Schaerf, A. (2023). Educational timetabling:
Problems, benchmarks, and state-of-the-art results. *European Journal of
Operational Research, 308*(1), 1–18.
https://doi.org/10.1016/j.ejor.2022.07.011

Chen, M. C., Sze, S. N., Goh, S. L., Sabar, N. R., & Kendall, G. (2021). A
survey of university course timetabling problem: Perspectives, trends and
opportunities. *IEEE Access, 9*, 106515–106529.
https://doi.org/10.1109/ACCESS.2021.3100613

Drake, J. H., Kheiri, A., Özcan, E., & Burke, E. K. (2020). Recent advances in
selection hyper-heuristics. *European Journal of Operational Research, 285*(2),
405–428. https://doi.org/10.1016/j.ejor.2019.07.073

Holm, D. S., Mikkelsen, R. Ø., Sørensen, M., & Stidsen, T. J. R. (2022). A
graph-based MIP formulation of the International Timetabling Competition 2019.
*Journal of Scheduling, 25*(4), 405–428.
https://doi.org/10.1007/s10951-022-00724-y

International Timetabling Competition 2019. (n.d.). *Problem format and
distribution constraints*. https://www.itc2019.org/format

International Timetabling Competition 2019. (n.d.). *Competition format DTD*.
https://www.itc2019.org/competition-format.dtd

Lemos, A., Monteiro, P. T., & Lynce, I. (2022). Introducing UniCorT: An
iterative university course timetabling tool with MaxSAT. *Journal of
Scheduling, 25*(4), 371–390.
https://doi.org/10.1007/s10951-021-00695-6

Lewis, R. (2008). A survey of metaheuristic-based techniques for university
timetabling problems. *OR Spectrum, 30*(1), 167–190.
https://doi.org/10.1007/s00291-007-0097-0

Müller, T., Rudová, H., & Müllerová, Z. (2025). Real-world university course
timetabling at the International Timetabling Competition 2019. *Journal of
Scheduling, 28*(2), 247–267.
https://doi.org/10.1007/s10951-023-00801-w

Google. (n.d.). *CP-SAT solver*. OR-Tools.
https://developers.google.com/optimization/cp/cp_solver

Sylejmani, K., Gashi, E., & Ymeri, A. (2023). Simulated annealing with
penalization for university course timetabling. *Journal of Scheduling,
26*(5), 497–517. https://doi.org/10.1007/s10951-022-00747-5

Metadata cross-check: Crossref and OpenAlex records were used for publication
titles, authors, dates, journals, issue/pages, and DOI. The citation for
Abdullah et al. was cross-checked using OpenAlex metadata and the cited
publisher DOI; report publication-page details should be rechecked against the
publisher record before formal submission.
