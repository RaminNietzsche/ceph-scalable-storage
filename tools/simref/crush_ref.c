/*
 * Reference harness for the web simulators' CRUSH port (tests only).
 *
 * It is compiled by tools/simref/gen_golden.py against an unmodified Ceph
 * source tree (CEPH_SRC) and links Ceph's own src/crush/{hash,crush,builder}.c;
 * src/crush/mapper.c is #included so the static crush_ln() can be dumped too.
 * Nothing from Ceph is copied into this file. Protocol: one command per line on
 * stdin, results on stdout (see gen_golden.py).
 */
#include "crush/mapper.c"
#include "crush/builder.h"
#include "crush/hash.h"

/* src/common/ceph_hash.cc is C++ by name but plain C inside (it only needs bool) */
#include <stdbool.h>
#include "common/ceph_hash.cc"

static int stable_mod(int x, int b, int bmask)   /* same contract as ceph_stable_mod() */
{
	if ((x & bmask) < b)
		return x & bmask;
	return x & (bmask >> 1);
}

int main(void)
{
	char cmd[16];
	struct crush_map *m = NULL;
	__u32 *w = NULL;
	int nw = 0;
	while (scanf("%15s", cmd) == 1) {
		if (!strcmp(cmd, "MAP")) {
			m = crush_create();
		} else if (!strcmp(cmd, "TUN")) {
			unsigned a, b, c, d, e, f;
			if (scanf("%u %u %u %u %u %u", &a, &b, &c, &d, &e, &f) != 6) return 2;
			m->choose_local_tries = a; m->choose_local_fallback_tries = b;
			m->choose_total_tries = c; m->chooseleaf_descend_once = d;
			m->chooseleaf_vary_r = e; m->chooseleaf_stable = f;
		} else if (!strcmp(cmd, "B")) {
			int id, type, n, idout;
			if (scanf("%d %d %d", &id, &type, &n) != 3) return 2;
			int *items = calloc(n ? n : 1, sizeof(int)), *ws = calloc(n ? n : 1, sizeof(int));
			for (int i = 0; i < n; i++) if (scanf("%d %d", &items[i], &ws[i]) != 2) return 2;
			struct crush_bucket *b = crush_make_bucket(m, CRUSH_BUCKET_STRAW2, CRUSH_HASH_DEFAULT, type, n, items, ws);
			if (crush_add_bucket(m, id, b, &idout) < 0) return 3;
			free(items); free(ws);
		} else if (!strcmp(cmd, "SCV")) {       /* SCV v: straw_calc_version (set_tunables_jewel sets 1) */
			unsigned v;
			if (scanf("%u", &v) != 1) return 2;
			m->straw_calc_version = v;
		} else if (!strcmp(cmd, "BA")) {        /* BA alg id type n (item weight)*: any bucket algorithm */
			int alg, id, type, n, idout;
			if (scanf("%d %d %d %d", &alg, &id, &type, &n) != 4) return 2;
			int *items = calloc(n ? n : 1, sizeof(int)), *ws = calloc(n ? n : 1, sizeof(int));
			for (int i = 0; i < n; i++) if (scanf("%d %d", &items[i], &ws[i]) != 2) return 2;
			struct crush_bucket *b = crush_make_bucket(m, alg, CRUSH_HASH_DEFAULT, type, n, items, ws);
			if (!b || crush_add_bucket(m, id, b, &idout) < 0) return 3;
			free(items); free(ws);
		} else if (!strcmp(cmd, "BW")) {        /* BW id: the bucket weight builder.c computed */
			int id;
			if (scanf("%d", &id) != 1) return 2;
			printf("%u\n", m->buckets[-1 - id]->weight);
		} else if (!strcmp(cmd, "BS")) {        /* BS id: the straw lengths of a straw bucket */
			int id;
			if (scanf("%d", &id) != 1) return 2;
			struct crush_bucket_straw *sb = (struct crush_bucket_straw *)m->buckets[-1 - id];
			for (unsigned i = 0; i < sb->h.size; i++) printf(i ? " %u" : "%u", sb->straws[i]);
			printf("\n");
		} else if (!strcmp(cmd, "BC")) {        /* BC id x rmax: crush_bucket_choose for r = 0..rmax-1, one workspace */
			int id, x, rmax;
			if (scanf("%d %d %d", &id, &x, &rmax) != 3) return 2;
			struct crush_work *cw = malloc(crush_work_size(m, 1));
			crush_init_workspace(m, cw);
			const struct crush_bucket *b = m->buckets[-1 - id];
			for (int r = 0; r < rmax; r++)
				printf(r ? " %d" : "%d", crush_bucket_choose(b, cw->work[-1 - id], x, r, NULL, 0));
			printf("\n");
			free(cw);
		} else if (!strcmp(cmd, "R")) {
			int no, type, n;
			if (scanf("%d %d %d", &no, &type, &n) != 3) return 2;
			struct crush_rule *r = crush_make_rule(n, type);
			for (int i = 0; i < n; i++) {
				int op, a1, a2;
				if (scanf("%d %d %d", &op, &a1, &a2) != 3) return 2;
				crush_rule_set_step(r, i, op, a1, a2);
			}
			if (crush_add_rule(m, r, no) < 0) return 3;
		} else if (!strcmp(cmd, "FIN")) {
			crush_finalize(m);
		} else if (!strcmp(cmd, "W")) {
			if (scanf("%d", &nw) != 1) return 2;
			free(w); w = calloc(nw ? nw : 1, sizeof(__u32));
			for (int i = 0; i < nw; i++) if (scanf("%u", &w[i]) != 1) return 2;
		} else if (!strcmp(cmd, "Q")) {          /* Q rule x0 count result_max [pgp pool] */
			int rule, x0, cnt, rmax, pgp, pool;
			if (scanf("%d %d %d %d %d %d", &rule, &x0, &cnt, &rmax, &pgp, &pool) != 6) return 2;
			int *res = calloc(rmax, sizeof(int));
			void *cw = malloc(crush_work_size(m, rmax));
			int mask = 1; while (mask < pgp) mask <<= 1; mask -= 1;
			for (int ps = x0; ps < x0 + cnt; ps++) {
				int x = pool >= 0 ? (int)crush_hash32_2(CRUSH_HASH_RJENKINS1, stable_mod(ps, pgp, mask), pool) : ps;
				crush_init_workspace(m, cw);
				int n = crush_do_rule(m, rule, x, res, rmax, w, nw, cw, NULL);
				printf("%d", n);
				for (int i = 0; i < n; i++) printf(" %d", res[i]);
				printf("\n");
			}
			free(res); free(cw);
		} else if (!strcmp(cmd, "END")) {
			crush_destroy(m); m = NULL;
		} else if (!strcmp(cmd, "H2")) {
			unsigned a, b;
			if (scanf("%u %u", &a, &b) != 2) return 2;
			printf("%u\n", crush_hash32_2(CRUSH_HASH_RJENKINS1, a, b));
		} else if (!strcmp(cmd, "H4")) {
			unsigned a, b, c, d;
			if (scanf("%u %u %u %u", &a, &b, &c, &d) != 4) return 2;
			printf("%u\n", crush_hash32_4(CRUSH_HASH_RJENKINS1, a, b, c, d));
		} else if (!strcmp(cmd, "H3")) {
			unsigned a, b, c;
			if (scanf("%u %u %u", &a, &b, &c) != 3) return 2;
			printf("%u\n", crush_hash32_3(CRUSH_HASH_RJENKINS1, a, b, c));
		} else if (!strcmp(cmd, "LN")) {        /* all 65536 crush_ln() values */
			for (unsigned u = 0; u <= 0xffff; u++) printf("%llu\n", (unsigned long long)crush_ln(u));
		} else if (!strcmp(cmd, "DRAW")) {      /* generate_exponential_distribution */
			int x, y, z, wt;
			if (scanf("%d %d %d %d", &x, &y, &z, &wt) != 4) return 2;
			printf("%lld\n", (long long)generate_exponential_distribution(CRUSH_HASH_RJENKINS1, x, y, z, wt));
		} else if (!strcmp(cmd, "STR")) {       /* STR <hex bytes or -> : rjenkins, then linux */
			char hex[1024];
			if (scanf("%1023s", hex) != 1) return 2;
			char buf[512]; int n = 0;
			if (strcmp(hex, "-"))
				for (int i = 0; hex[i] && hex[i + 1]; i += 2) { unsigned v; sscanf(hex + i, "%2x", &v); buf[n++] = (char)v; }
			printf("%u\n", ceph_str_hash_rjenkins(buf, n));
			printf("%u\n", ceph_str_hash_linux(buf, n));
		} else {
			fprintf(stderr, "bad command %s\n", cmd);
			return 2;
		}
	}
	return 0;
}
