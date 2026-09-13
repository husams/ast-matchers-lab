// OpenMP sample for Part 11. Compile with -fopenmp -fopenmp-version=51
// (default(private) / default(firstprivate) are OpenMP 5.1 additions).

int work(int n) {
  int sum = 0;

#pragma omp parallel
  ;

#pragma omp parallel
  {}

#pragma omp parallel default(none)
  {}

#pragma omp parallel default(shared)
  {}

#pragma omp parallel default(private)
  {}

#pragma omp parallel default(firstprivate)
  {}

#pragma omp parallel for
  for (int i = 0; i < n; ++i)
    sum += i;

#pragma omp for
  for (int i = 0; i < n; ++i)
    sum += i;

#pragma omp taskyield

#pragma omp barrier

#pragma omp target update to(sum)

#pragma omp target update from(sum)

  return sum;
}
