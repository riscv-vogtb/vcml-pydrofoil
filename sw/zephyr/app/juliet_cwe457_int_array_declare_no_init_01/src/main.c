/*
 * CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01:
 * good() fully initializes the stack array before reading it and must run to
 * completion; bad() reads it without initializing and is expected to trip
 * the stack-poisoning read fault.
 */

#include <stdio.h>

extern void CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_good(void);
extern void CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_bad(void);

int main(void)
{
	printf("Calling good()...\n");
	CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_good();
	printf("Finished good()\n");

	printf("Calling bad()...\n");
	CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_bad();
	printf("Finished bad()\n");

	return 0;
}
