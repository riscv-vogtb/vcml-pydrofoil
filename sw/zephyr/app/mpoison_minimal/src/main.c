#include <stdio.h>

static int trigger(void)
{
	int buf[16];
	buf[0] = 1;
	return buf[1];
}

int main(void)
{
	printf("calling trigger()...\n");
	int result = trigger();
	printf("trigger() returned %d\n", result);
	return 0;
}
