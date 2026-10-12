/**
 * A micro benchmark program that has no false sharing.
 *
 * gem5 SE-mode version for 2 cores:
 *   Core 0 -> main thread runs worker 0
 *   Core 1 -> pthread runs worker 1
 */

#define _GNU_SOURCE

#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#ifdef ROI_TRACING
#include "m5_library/hooks_prospar.h"

#endif

#ifdef SE_MODE_BUILD
#include "gem5/m5ops.h"

#endif

#define NUM_THREADS 2

int loop_count __attribute__((aligned(64))) = 0;

void *without_fs(void *);

/*
 * 4 bytes per uint32_t.
 *
 * index 0  -> offset 0 bytes
 * index 16 -> offset 64 bytes
 *
 * Therefore each worker writes to a different 64-byte cache line.
 */
volatile uint32_t array_without_fs[NUM_THREADS * 16]
    __attribute__((aligned(64))) = {0};


/*
 * BEHAVIOR:
 * NO FALSE SHARING
 * NO TRUE SHARING
 */
void *without_fs(void *threadId)
{
    int currID = (int)(intptr_t)threadId;

    for (uint32_t i = 0; i < (uint32_t)loop_count; i++) {
        array_without_fs[currID * 16] += 1;
    }

    printf(
        "thread %d output %u\n",
        currID,
        array_without_fs[currID * 16]
    );

    return NULL;
}


int main(int argc, char *argv[])
{
    /*
     * Set number of loop iterations.
     *
     * Example:
     *   ./no-false-sharing 21
     *
     * gives:
     *   2^21 = 2097152 iterations
     */
    if (argc == 2) {
        loop_count = (1 << atoi(argv[1]));
    } else {
        loop_count = (1 << 18);
    }


    /*
     * We only create ONE pthread.
     *
     * Main thread = worker 0
     * pthread     = worker 1
     *
     * This avoids requiring 3 gem5 thread contexts.
     */
    pthread_t thread;

    clock_t start_time;
    clock_t end_time;


    printf(
        "Starting address of array without FS : %p\n",
        (void *)array_without_fs
    );

    printf(
        "Address of loop_count var: %p\n",
        (void *)&loop_count
    );

    printf(
        "Thread 0 counter address: %p\n",
        (void *)&array_without_fs[0]
    );

    printf(
        "Thread 1 counter address: %p\n",
        (void *)&array_without_fs[16]
    );


    /*
     * Initialize the actual locations used by the workers.
     */
    for (uint32_t i = 0; i < NUM_THREADS; i++) {
        array_without_fs[i * 16] = 0;
    }


    start_time = clock();


#ifdef ROI_TRACING
    roi_begin();
#endif

#ifdef SE_MODE_BUILD
    m5_reset_stats(0, 0);
#endif


    /*
     * Create worker 1.
     *
     * In a 2-core gem5 SE configuration:
     *
     *     core 0 -> main
     *     core 1 -> this pthread
     */
    int ret = pthread_create(
        &thread,
        NULL,
        without_fs,
        (void *)(intptr_t)1
    );

    if (ret != 0) {
        fprintf(
            stderr,
            "pthread_create failed with error %d\n",
            ret
        );

        return 1;
    }


    /*
     * Main thread acts as worker 0.
     *
     * This means we have only two active software threads:
     *
     *     main      -> worker 0
     *     pthread   -> worker 1
     */
    without_fs((void *)(intptr_t)0);


    /*
     * Wait for worker 1.
     */
    ret = pthread_join(thread, NULL);

    if (ret != 0) {
        fprintf(
            stderr,
            "pthread_join failed with error %d\n",
            ret
        );

        return 1;
    }


#ifdef ROI_TRACING
    roi_end();
#endif


    end_time = clock();


    printf(
        "Time to completion: %f seconds\n",
        (double)(end_time - start_time) / CLOCKS_PER_SEC
    );


#ifdef SE_MODE_BUILD
    m5_dump_stats(0, 0);
#endif


    /*
     * Correctness check.
     */
    for (int i = 0; i < NUM_THREADS; i++) {

        if (array_without_fs[i * 16] != (uint32_t)loop_count) {

            printf(
                "Diff found for index: %d "
                "actual value: %u "
                "expected value: %d\n",
                i,
                array_without_fs[i * 16],
                loop_count
            );
        }
    }


    printf("Benchmark completed successfully.\n");

    return 0;
}
