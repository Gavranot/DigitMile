# Estimating Weekly System Load for an EdTech Game in North Macedonian Primary Schools

## Executive summary

This report derives a realistic load model for an online game used as part of the IT/informatics curriculum in grades 3–5 across primary schools in North Macedonia.
It combines official school statistics, curriculum structure, and typical timetable patterns to give formulae and concrete scenarios for weekly traffic and peak concurrency, which can be plugged into load‑testing tools.

Under current demographics, there are about 182,124 pupils in regular primary and lower‑secondary schools (grades 1–9) and 19,848 first‑graders at the start of the 2023/24 school year.[^1]
Assuming roughly even cohort sizes across the nine grades, grades 3–5 together represent approximately 60,000 potential users.
For adoption rates of 25–75% of this cohort, and assuming one 45‑minute game‑based IT lesson per week per student with 90–95% attendance, expected in‑class weekly sessions range from about 14,000 to 42,000.

Spreading these sessions across around 30 weekly lesson slots and applying a realistic peak factor of 1.5–2.0 for timetable clustering leads to estimated peak concurrency in the range of roughly 800–2,400 simultaneous student users, depending on adoption.
For a moderately chatty web application that produces 6–10 requests per active user per minute, this translates into peak loads on the order of 130–400 HTTP requests per second (RPS) during the busiest school periods.
These figures provide a defendable basis for configuring benchmarking tools such as k6, Locust, or JMeter.

## Education system and population baseline

### Structure of primary education

North Macedonia’s primary and lower‑secondary education is organized as a single nine‑year cycle, covering ages approximately 6 to 14, and is compulsory and free for all children.[^2][^3]
The concept for nine‑year primary education divides schooling into three periods: grades 1–3, grades 4–6, and grades 7–9, with the early grades taught by class teachers and later grades by subject specialists.[^4][^2]
This three‑period structure is relevant because IT/informatics and broader digital skills are introduced and reinforced across these cycles.

### Number of schools

According to the Eurydice profile, in the late 2010s there were 988 primary schools in the country when satellite schools are included, with 363 primary schools counted as legal entities.[^5][^2]
The legal‑entity figure (roughly 350–400 institutions) is a realistic upper bound for the number of distinct schools that might sign up for a platform contract, whereas the larger number including affiliates better reflects the total number of separate teaching sites and computer labs.
This justifies modelling "hundreds of schools" as a plausible national‑scale deployment.

### Number of primary pupils and grade sizes

Official statistics from the State Statistical Office show that at the beginning of the 2023/24 school year there were 182,124 students enrolled in regular primary and lower‑secondary schools (grades 1–9).[^1]
In the same year, 19,848 students enrolled in first grade.[^1]
If grade‑level cohorts are broadly similar in size (which is supported by time‑series data on primary enrolment that fluctuate only modestly year to year), then a single grade has roughly 20,000 students, and grades 3–5 combined represent about 60,000 potential users.

For modelling, this report uses the following approximations anchored in the official numbers:

- Total grades 1–9 pupils: \(P_{1-9} \approx 182{,}000\).[^1]
- Approximate pupils per grade: \(P_{g} \approx P_{1-9}/9 \approx 20{,}000\).
- Grades 3–5 combined: \(P_{3-5} \approx 3 \times P_{g} \approx 60{,}000\).

These approximations remain within a few percent of the official first‑grade figure and are adequate for capacity planning.

## Curriculum, informatics, and timetable patterns

### Curriculum reforms and digital competencies

North Macedonia has been implementing a new "Concept for Primary Education" since the 2021/22 school year, starting with grades 1 and 4 and then rolling it out gradually to other grades over about five years.[^6][^7]
The reform reduces the number of discrete subjects by integrating them into broader areas, aims to promote deeper, competence‑based learning, and explicitly emphasises digital skills and project‑based work.[^7][^6]
As a result, informatics and ICT are present both as dedicated subjects in some grades and as integrated use of ICT in other subjects.

A prior academic analysis of informatics teaching under the earlier curriculum noted that the number of teaching hours for the dedicated informatics subject in the nine‑year primary education was "very small", specifically 2 classes per week in grade 6 and 1 class per week in grade 7.[^8]
Although this study did not cover the newer concept or grades 3–5 directly, it indicates that dedicated informatics lessons are limited to around 1–2 weekly periods per grade, rather than a high‑intensity daily course.[^8]
Given the reform’s goal of integrating digital competences rather than drastically increasing dedicated ICT hours, taking 1–2 game‑based lessons per week per class as a design range is reasonable.

### Weekly hours and daily structure

Guidance materials related to the new concept illustrate that younger primary grades typically have on the order of 22–27 teaching hours per week, with additional time in school for breaks and supervised activities, adding up to roughly 5 school hours per day.[^9]
This is consistent with broader encyclopedic descriptions of Macedonian primary education, which describe about 5–6 lessons of 40–45 minutes per day across a five‑day week.[^10][^3]
Schools often operate in one or two shifts (morning and afternoon), with different classes attending in different shifts due to building capacity.

From a load‑modelling perspective, this implies there are roughly:

- 5–6 teaching blocks per day.
- 5 days per week.
- Around 25–30 lesson blocks per week during which ICT‑based lessons could be scheduled.

The exact number of potential slots per school depends on shift configuration and lab capacity, but this 25–30 block range provides a useful normalisation factor for estimating concurrency from weekly session counts.

### Informatics and ICT access constraints

The same academic analysis that criticised the limited hours for dedicated informatics also highlighted resource constraints, such as limited numbers of computers and insufficient equipment relative to the government’s digitalisation goals.[^8]
Reports on the state of e‑learning in the country similarly note uneven ICT infrastructure across schools and a need for investment in networks and digital content.[^11]
In practice, this means that many classes will use shared computer labs with 15–30 workstations, and lessons may be staggered between parallel classes when there are multiple sections per grade.

These constraints push schools to schedule IT game usage in discrete blocks (e.g., one lab lesson per class per week) rather than continuous background usage throughout the day.
This reinforces the choice to model a small number of weekly sessions per student and to assume that load concentrates during specific class periods.

## Usage model for the game

### Parameters and notation

For capacity planning, it is useful to define the following parameters:

- \(P_{3-5}\): total number of pupils in grades 3–5 nationally (\(\approx 60{,}000\)).[^1]
- \(p\): adoption proportion of the national grade 3–5 cohort using the game (0–1).
- \(S = p \times P_{3-5}\): number of distinct student users reached.
- \(f\): average number of in‑class game sessions per student per week (1–2).
- \(a\): effective attendance/participation rate during those sessions (e.g., 0.90–0.95).
- \(w\): number of active curriculum weeks per year using the game (e.g., 8–12 weeks for 2–3 months of use).
- \(L\): duration of a single session in minutes (e.g., 40–45 minutes).
- \(H\): effective number of lesson blocks per week across which these sessions are distributed (e.g., \(H \approx 30\)).
- \(B_{\text{peak}}\): peak factor capturing clustering of sessions in time (e.g., 1.5–2.0).
- \(r_m\): average number of HTTP requests per minute generated by an active student (end‑to‑end, including asset loads not cached at the edge).

The platform may also involve teachers and administrators, but their traffic volumes are small compared with student traffic and can be modelled separately.

### Weekly student sessions

The total number of individual student game sessions per week across all schools is:

\[
N_{\text{sess}} = S \times f \times a. \quad (1)
\]

For example, with \(P_{3-5} \approx 60{,}000\), \(p = 0.5\), \(f = 1\), and \(a = 0.93\):

- \(S = 0.5 \times 60{,}000 = 30{,}000\) students.
- \(N_{\text{sess}} = 30{,}000 \times 1 \times 0.93 \approx 27{,}900\) weekly student sessions.

If the curriculum uses the game twice a week for shorter activities (\(f = 2\)), then weekly sessions double.

### Average and peak concurrency during school hours

Assuming that these \(N_{\text{sess}}\) sessions are spread across \(H\) possible lesson blocks per week, a baseline estimate of average concurrent in‑class users per block is:

\[
U_{\text{avg}} = \frac{N_{\text{sess}}}{H}. \quad (2)
\]

Because schools do not schedule IT lessons perfectly uniformly over all 25–30 blocks, some clustering will occur (e.g., many schools favouring certain days or time slots, or multiple grades using the lab back‑to‑back).
To account for this, introduce a peak factor \(B_{\text{peak}}\) to obtain peak concurrency:

\[
U_{\text{peak}} = B_{\text{peak}} \times U_{\text{avg}}. \quad (3)
\]

For example, with the earlier numbers (\(N_{\text{sess}} \approx 27{,}900\)), \(H = 30\), and \(B_{\text{peak}} = 1.7\):

- \(U_{\text{avg}} \approx 27{,}900 / 30 \approx 930\) concurrent students.
- \(U_{\text{peak}} \approx 1.7 \times 930 \approx 1{,}580\) peak concurrent students.

The choice of \(H\) and \(B_{\text{peak}}\) determines how aggressive the concurrency estimate is.
Taking \(H = 25\) and \(B_{\text{peak}} = 2\) would yield higher peaks; taking \(H = 35\) and \(B_{\text{peak}} = 1.5\) would reduce them.

### Translating concurrency into peak RPS

Given a peak concurrency estimate \(U_{\text{peak}}\) and an estimate of per‑user chattiness \(r_m\) (requests per active minute per user), the peak request rate in requests per second is:

\[
\text{RPS}_{\text{peak}} = \frac{U_{\text{peak}} \times r_m}{60}. \quad (4)
\]

If the game is well‑optimised and uses a combination of HTTP caching and long‑lived WebSocket or WebRTC connections, it might generate as few as 3–6 HTTP requests per minute per user.
For a more traditional web app with frequent AJAX calls, 8–12 requests per minute per user is plausible.

Continuing the example with \(U_{\text{peak}} \approx 1{,}580\):

- At \(r_m = 6\): \(\text{RPS}_{\text{peak}} \approx 1{,}580 \times 6 / 60 \approx 158\) RPS.
- At \(r_m = 10\): \(\text{RPS}_{\text{peak}} \approx 1{,}580 \times 10 / 60 \approx 263\) RPS.

These figures should be used as inputs to load‑testing scenarios, with additional safety margins to account for traffic bursts at login time and occasional self‑directed use by students outside scheduled classes.

## Scenario analysis

### Adoption scenarios

Using the national grade 3–5 population estimate \(P_{3-5} \approx 60{,}000\), consider three adoption levels:

- **Low**: \(p = 0.25\) (about a quarter of all grade 3–5 pupils use the game).
- **Medium**: \(p = 0.50\).
- **High**: \(p = 0.75\).

Assume for these scenarios:

- \(f = 1\) in‑class session per student per week.
- \(a = 0.93\) attendance.
- \(H = 30\) lesson blocks per week.
- \(B_{\text{peak}} = 1.7\).

The table below summarises derived student‑side metrics.

| Scenario | Adoption \(p\) | Students \(S\) | Weekly sessions \(N_{\text{sess}}\) | Avg concurrent \(U_{\text{avg}}\) | Peak concurrent \(U_{\text{peak}}\) |
|---------|-------------|------------------|------------------------------|-------------------------------|--------------------------------|
| Low     | 0.25        | 15,000           | 13,950                       | 465                           | 790                            |
| Medium  | 0.50        | 30,000           | 27,900                       | 930                           | 1,580                          |
| High    | 0.75        | 45,000           | 41,850                       | 1,395                         | 2,370                          |

All figures are approximations anchored on \(P_{3-5} \approx 60{,}000\) derived from official statistics.[^1]
The concurrency numbers are approximate planning targets rather than precise predictions.

### RPS ranges per scenario

Using equation (4), peak RPS can be derived for different assumptions about \(r_m\).
The following table shows RPS bands for each adoption scenario and two chattiness levels (6 and 10 requests per minute per user):

| Scenario | Peak concurrent \(U_{\text{peak}}\) | \(r_m = 6\) (RPS) | \(r_m = 10\) (RPS) |
|----------|-------------------------------|----------------------|-----------------------|
| Low      | 790                           | ~79                  | ~132                  |
| Medium   | 1,580                         | ~158                 | ~263                  |
| High     | 2,370                         | ~237                 | ~395                  |

When designing benchmarks, these can be treated as baseline peaks and then multiplied by a safety factor (e.g., 1.3–2.0x) to cover unanticipated swings such as many schools synchronising their IT lessons on the same day or spikes at the start of a term.

### Teacher and admin traffic

Teacher and administrative traffic are much smaller in volume than student traffic but should be considered for endpoint diversity and data‑integrity testing.
Official statistics report around 11,000–12,000 teachers employed in primary education, though exact counts vary by year and definition.[^12][^1]
Even if every teacher interacts with the platform several times per day, the resulting requests are negligible compared with thousands of concurrent student game sessions.

However, teacher actions often touch more sensitive operations (creating classes, updating curriculum content, exporting reports), so benchmarks should include:

- Occasional bursts of teacher logins and navigation around lesson start times.
- Bulk operations such as loading dashboards or exporting results for entire classes.
- Administrative maintenance windows with relatively low concurrency but high write intensity.

These can be layered on top of the student‑load scenarios at low additional RPS (e.g., 5–20 RPS) without materially affecting capacity planning.

## Benchmark design recommendations

### Translate into k6/Locust/JMeter parameters

The scenario tables can be mapped directly to virtual‑user (VU) and arrival‑rate configurations in common load‑testing tools:

- For a given scenario, set the **target concurrency** (VU count) to \(U_{\text{peak}}\) multiplied by a safety margin (e.g., 1.5x).
- For arrival‑rate or constant‑arrival‑rate tests, set the **target RPS** to the corresponding RPS band (e.g., medium‑adoption, \(r_m = 10\): target ~260–400 RPS).
- Use **ramp‑up stages** (e.g., 10–15 minutes) to simulate classes gradually joining at the start of a lesson rather than a pure step function.
- Model **think time** (delays between user actions) so that the average per‑user chattiness matches the assumed \(r_m\).

Example: For a medium‑adoption scenario with a safety factor of 1.5 and \(r_m = 8\):

- Target VUs \(\approx 1.5 \times 1{,}580 \approx 2{,}400\).
- Target RPS \(\approx 1{,}580 \times 8 / 60 \approx 210\); with safety factor, design for ~320 RPS.

### Model temporal patterns realistically

In addition to simple "flat" sustained‑load tests, it is advisable to design test patterns that mirror the school day:

- **Morning spike**: ramp from near‑zero to target concurrency over 30–60 minutes, hold for 1–2 hours, then drop.
- **Mid‑day plateau**: smaller second spike if afternoon shifts or additional ICT lessons are common.
- **Evening/off‑hours**: low background load (e.g., 1–5% of peak) to represent self‑directed student use and occasional teacher preparation.

This helps uncover resource‑pool exhaustion, connection‑reuse issues, and instance auto‑scaling behaviour under realistic daily cycles rather than purely synthetic constant load.

### Account for network and device variability

Reports on e‑learning and digital infrastructure in North Macedonia emphasise disparities in connectivity and equipment across schools and regions.[^13][^11]
Some students will access the game from well‑connected urban schools with modern devices; others may be on older hardware and less reliable connections.

When designing benchmarks, consider:

- Testing with **higher latency** and **packet loss** profiles to mimic less reliable connections.
- Ensuring correct handling of **retries** and **idempotent writes** so that intermittent failures do not multiply server‑side load unexpectedly.
- Using **content‑delivery networks (CDNs)** and edge caching for static assets so that the server‑side benchmarks focus on dynamic requests and game state.

### Data and state considerations

Since students will typically use the game repeatedly over 8–12 weeks as part of the curriculum, the platform must handle not only concurrent activity but also cumulative data growth and state management.
Benchmarks should therefore include:

- Tests on **cold data** (empty or small databases) and **warm data** (millions of records) to observe performance degradation trends.
- Simulated **grade‑book and progress‑tracking writes** proportional to class sizes (e.g., 20–30 write operations per class per session).
- **Idempotency and consistency** checks under concurrent writes from multiple devices in the same class.

## Limitations and further refinement

The modelling in this report is constrained by the level of publicly available detail about the exact weekly hours for informatics or game‑based IT activities specifically in grades 3–5 under the newest curriculum.[^6][^8]
Available sources confirm the overall structure (nine‑year primary, three periods, modest dedicated informatics hours, and integrated digital competences) but do not give a definitive number of weekly IT hours for each of grades 3–5.

To refine the model, the following data would be especially valuable:

- Official, grade‑by‑grade timetables from the Bureau for Development of Education for informatics and digital‑skills‑related subjects in grades 3–5.
- Typical **class sizes** (students per section) and **number of parallel sections per grade** in representative schools (urban vs rural, mono‑ vs multi‑shift).
- Real usage logs from a pilot deployment of the game, including **per‑session request traces** and **session duration distributions**.

Until such data are available, the scenarios and formulae provided here offer a transparent, evidence‑anchored basis for capacity planning and benchmarking for an IT‑class game deployed across hundreds of primary schools in North Macedonia.

---

## References

1. [Key takeaway](https://www.stat.mk/en/stat/population-and-living-conditions/education/primary-lower-secondary-and-upper-secondary-schools-at-the-beginning-of-the-school-year/primary-lower-secondary-and-upper-secondary-schools-at-the-beginning-of-the-school-year-20232024/)

2. [Organisation of the education system and of its structure](https://eurydice.eacea.ec.europa.eu/eurypedia/republic-north-macedonia/organisation-education-system-and-its-structure) - The education system of North Macedonia is comprised of pre-school education, primary education, sec...

3. [Education in North Macedonia](https://en.wikipedia.org/wiki/Education_in_North_Macedonia) - The Constitution of North Macedonia mandates free and compulsory primary and secondary education in ...

4. [[PDF] North Macedonia | PIRLS 2021](https://pirls2021.org/wp-content/uploads/2022/10/North-Macedonia.pdf) - Municipalities were given the authority to establish primary and secondary schools, maintain the sch...

5. [Statistics on educational institutions - What is Eurydice?](https://eurydice.eacea.ec.europa.eu/eurypedia/republic-north-macedonia/statistics-educational-institutions) - Statistics on educational institutions providing pre-primary, primary, secondary (and post-secondary...

6. [Концепцијата за основно образование ќе почне да се применува во прво и четврто одделение](https://kajgana.com/koncepcijata-za-osnovno-obrazovanie-ke-pochne-da-se-primenuva-vo-prvo-i-chetvrto-oddelenie) - Скопје, 12 август 2021 (МИА) – Концепцијата за основно образование, која овој март беше усвоена по ч...

7. [Концепцијата за основно образование ќе почне да се применува во прво и четврто одделение - telma.com.mk](https://telma.com.mk/2021/08/12/%D0%BA%D0%BE%D0%BD%D1%86%D0%B5%D0%BF%D1%86%D0%B8%D1%98%D0%B0%D1%82%D0%B0-%D0%B7%D0%B0-%D0%BE%D1%81%D0%BD%D0%BE%D0%B2%D0%BD%D0%BE-%D0%BE%D0%B1%D1%80%D0%B0%D0%B7%D0%BE%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5/) - Концепцијата за основно образование, која овој март беше усвоена по четири месеци дебати и полемики,...

8. [INFORMATICS IN PRIMARY AND SECONDARY SCHOOLS](https://ciit.finki.ukim.mk/data/papers/9CiiT/9CiiT-72.pdf)

9. [модул 3](https://aidafizika.wordpress.com/wp-content/uploads/2022/04/modul_3.pdf) - на часови за ист предмет. Различни предмети. (пр. Техничко образование и информатика). Додека едните...

10. [North Macedonia](https://timssandpirls.bc.edu/timss2019/encyclopedia/pdf/North%20Macedonia.pdf) - by B Lameva · Cited by 4 — Children start school roughly at the age of 5 1/2. Primary education last...

11. [situation with e- learning in macedonia](https://metamorphosis.org.mk/wp-content/uploads/2014/09/Situation-with-e-Learning-in-Macedonia.pdf)

12. [The number of students in primary and secondary schools ...](https://telegrafi.com/en/ulet-numri-nxenesve-ne-shkollat-fillore-dhe-te-mesme-ne-maqedonine-e-veriut-2/) - In North Macedonia, the number of students in primary schools has decreased by 1.6 percent and in se...

13. [[PDF] DIGITALSKILLSASSESSMENT REPUBLICOFNORTHMACEDONIA](https://northmacedonia.un.org/sites/default/files/2022-04/ITU_NorthMacedonia_DigitalSkillsAssessment_20211223_FINAL.pdf) - This initiative is part of a long-standing national effort to introduce e-government solutions in No...

