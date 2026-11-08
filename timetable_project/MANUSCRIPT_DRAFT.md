# Incremental Constraint Validation and Variable Ordering for University Timetabling

**Manuscript status:** Working draft. Results are preliminary; neither search timeout establishes instance infeasibility.

## Abstract

This study examines a finite-domain constraint satisfaction approach to university course timetabling using the ITC 2019 instance `pu-d5-spr17`. The instance contains 1,061 classes and 84 rooms. The solver represents each class as a variable whose domain consists of feasible placements, checks room conflicts and required distribution constraints, and applies forward checking. A standards-grounded correction made required `NotOverlap` and `SameAttendees` checks incremental over assigned class pairs, allowing violations to be detected before every member of a distribution is assigned. A static variable-ordering baseline reached 306 assigned classes (28.84%) within 300 seconds. A dynamic minimum-remaining-values (MRV) variant reached 86 classes in approximately the same time because recomputing legal domains dominated its runtime. Neither run produced a complete timetable; feasibility therefore remains undetermined. The experiment suggests that exact dynamic MRV, when implemented by rescanning all current domains at every search node, is computationally costly for this instance. Further work will focus on reducing repeated validation while preserving the verified hard-constraint semantics.

## 1. Introduction

University course timetabling assigns classes to times and, where required, rooms while respecting institutional requirements. Large benchmark instances combine broad placement domains with constraints that couple classes through shared rooms, attendees, instructors, or distribution rules. A search method must therefore balance the cost of choosing a variable, validating candidate placements, and pruning branches that cannot be extended.

This work studies a constraint satisfaction solver on a single ITC 2019 benchmark instance. The immediate research question is whether dynamic MRV improves progress over a static domain-size approximation when both use the same candidate ordering, hard constraints, dataset, and 300-second limit. The purpose is diagnostic: a partial assignment is not evidence that the full instance is infeasible, and a timed-out best partial schedule is not a feasible timetable.

## 2. Literature review

Automated timetabling covers several related but non-identical scheduling problems. Foundational surveys describe its problem families and the evolution of automated methods (Schaerf, 1999), while later reviews summarize research directions and the use of optimization and metaheuristics (Burke & Petrovic, 2002). A recent educational-timetabling review further distinguishes problem families, benchmarks, and state-of-the-art results (Ceschia et al., 2023). University timetabling has a particularly substantial metaheuristic literature (Lewis, 2008). These reviews motivate constraint-based and local-search approaches, but their results span different problem definitions and should not be treated as directly comparable without matching constraints, data, and evaluation protocols.

Constraint programming has been applied directly to university timetabling, including a constraint logic programming formulation (Goltz & Matzke, 1998). At the other end of the optimization spectrum, simulated annealing has been studied for school timetabling (Abramson, 1991); this provides relevant local-search context but concerns a different scheduling setting. More recent benchmark-specific work includes graph-based mixed-integer programming for ITC 2019 (Holm et al., 2022). The ITC 2019 benchmark itself reflects real-world university course timetabling, where student sectioning interacts with time and room assignment, as documented by Müller et al. (2025). Together these studies establish that formulation and instance semantics matter: algorithm comparisons are meaningful only when the benchmark, constraint interpretation, resource assumptions, and success criteria are aligned.

The present experiment is narrower than these broader studies. It evaluates two variable-selection strategies on one parsed ITC 2019 instance under one fixed time budget; it does not compare against the published MIP or metaheuristic results, and it does not evaluate local search or solution quality because no complete feasible timetable has yet been found.

## 3. Problem and verified constraint semantics

The benchmark used here is `pu-d5-spr17`, parsed into 1,061 class variables and 84 rooms. Each class has a finite initial domain of placement candidates. The solver rejects candidates that conflict with an assigned class in the same room or violate a required distribution involving the class.

The [official ITC 2019 format](https://www.itc2019.org/format#NotOverlap) defines `NotOverlap` for every pair of classes in the distribution: two classes must not overlap in time-of-day, days of the week, or weeks. It defines `SameAttendees` pairwise as well: classes must not overlap, and when their day and week sets intersect, the assigned locations must permit adequate travel in either temporal direction (International Timetabling Competition, n.d.). The current validator checks assigned pairs immediately, even when other distribution members remain unassigned. This is safe for these pairwise requirements because a violation among two already-fixed members cannot be repaired by assigning a third member. The `SameAttendees` predicate uses directional room travel and accepts the exact travel-time boundary.

## 4. Method

The solver searches a finite-domain CSP. Static selection chooses an unassigned class by original domain size, breaking ties by total constraint-graph degree, then calculates legal placements for that class. Dynamic MRV instead calculates current legal placements for every unassigned class at each search node, chooses the smallest legal domain, and breaks ties by the number of unassigned neighbors. The static and dynamic strategies are selectable through the command-line strategy option; static remains the default, making the experimental change reversible.

Both strategies retain the same candidate ordering, required hard constraints, forward-checking behavior, node limit, and 300-second wall-clock limit. No validation cache was used. The resulting comparison isolates variable selection but does not establish a general performance ranking from a single run.

Constraint validation is covered by regression cases for partial and complete `NotOverlap` and `SameAttendees` distributions, including common-day/week conditions and directional travel boundaries. The full 20-test suite passes. The solved-result reporting path was also aligned with the validator's actual dictionary return shape and tested on a complete feasible synthetic schedule.

## 5. Experimental setup

The experiment uses the `pu-d5-spr17` dataset, a 300-second solver time limit, and the existing node limit of 1,000,000. The program runs deterministically in the observed configuration; no random seed is used by the search. A run is considered successful only if the solver assigns all classes and its final hard-constraint validator reports feasibility. A timeout is reported as incomplete, not infeasible.

## 6. Preliminary results

| Strategy | Runtime (s) | Assigned classes | Coverage | Search nodes | Backtracks | Complete validated timetable |
|---|---:|---:|---:|---:|---:|---|
| Static MRV baseline | 300.002 | 306 / 1,061 | 28.84% | 103,373 | 103,200 | No; feasibility not determined |
| Dynamic MRV | 303.400 | 86 / 1,061 | 8.11% | 87 | 86 | No; feasibility not determined |

In the static run, candidate validation was called 5,792,723 times (206.995 cumulative seconds); forward checking took 139.003 cumulative seconds over 287,679 calls. All 184,307 recorded forward-check failures were attributed to class 573 leaving class 576 with no legal candidate at the 306-class frontier. In the dynamic run, variable selection took 303.361 cumulative seconds in 87 calls. Candidate validation was called 6,855,214 times, with 281.625 cumulative seconds. The solver exceeded the nominal limit by 3.400 seconds because the current outer time check does not interrupt a variable-selection scan. These figures indicate that this straightforward exact-MRV implementation spends too much of the runtime recalculating legal domains to advance the search effectively.

The complete console outputs are preserved in [the static run log](./results/solver_static_2026-10-17.txt) and [the dynamic run log](./results/solver_dynamic_2026-10-17.txt).

The static result is the stronger search-progress baseline in these observed runs, but neither result is a complete solution. These measurements do not support a claim of feasibility or infeasibility, and there is not yet a valid timetable on which to evaluate soft objectives or local search.

## 7. Limitations and next steps

The current evidence is limited to one benchmark instance and one run per strategy. The implementations include diagnostic instrumentation, and selection and candidate-validation costs are cumulative inclusive timings that overlap. A repeated validation path remains a performance target, but any future optimization must preserve the current assignment-state semantics and be tested against the regression cases. Before reporting benchmark conclusions, the experiment should be repeated under a documented environment and the hard constraints should be independently checked for any complete solution.

Local search, student-facing quality measures, and soft-penalty comparisons are out of scope until a complete feasible starting timetable is obtained or a separately justified repair approach is implemented.

## References

Abramson, D. (1991). Constructing school timetables using simulated annealing: Sequential and parallel algorithms. *Management Science, 37*(1), 98–113. https://doi.org/10.1287/mnsc.37.1.98

Burke, E. K., & Petrovic, S. (2002). Recent research directions in automated timetabling. *European Journal of Operational Research, 140*(2), 266–280. https://doi.org/10.1016/S0377-2217(02)00069-3

Ceschia, S., Di Gaspero, L., & Schaerf, A. (2023). Educational timetabling: Problems, benchmarks, and state-of-the-art results. *European Journal of Operational Research, 308*(1), 1–18. https://doi.org/10.1016/j.ejor.2022.07.011

Goltz, H.-J., & Matzke, D. (1998). University timetabling using constraint logic programming. In G. Gupta (Ed.), *Practical aspects of declarative languages* (pp. 320–334). Springer. https://doi.org/10.1007/3-540-49201-1_22

Holm, D. S., Mikkelsen, R. Ø., Sørensen, M., & Stidsen, T. J. R. (2022). A graph-based MIP formulation of the International Timetabling Competition 2019. *Journal of Scheduling, 25*(4), 405–428. https://doi.org/10.1007/s10951-022-00724-y

International Timetabling Competition. (n.d.). *ITC 2019: Format*. https://www.itc2019.org/format

Lewis, R. (2008). A survey of metaheuristic-based techniques for university timetabling problems. *OR Spectrum, 30*(1), 167–190. https://doi.org/10.1007/s00291-007-0097-0

Müller, T., Rudová, H., & Müllerová, Z. (2025). Real-world university course timetabling at the International Timetabling Competition 2019. *Journal of Scheduling, 28*(2), 247–267. https://doi.org/10.1007/s10951-023-00801-w

Schaerf, A. (1999). A survey of automated timetabling. *Artificial Intelligence Review, 13*(2), 87–127. https://doi.org/10.1023/A:1006576209967
