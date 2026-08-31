// Fallback testcase, used when tools/juliet has not generated one into the build directory.
#include "CWE457_Use_of_Uninitialized_Variable/s01/CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01.c"

const char *juliet_case_name = "int_array_declare_no_init_01";
const char *juliet_phase = "bad";

void juliet_run(void)
{
	CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_bad();
}
