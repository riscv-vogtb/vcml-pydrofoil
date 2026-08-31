// Fallback testcase, used when tools/juliet has not generated one into the build directory. 
#include "CWE457_Use_of_Uninitialized_Variable/s01/CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01.c"

const char *juliet_case_name =
	"CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01";

void juliet_bad(void)
{
	CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_bad();
}

void juliet_good(void)
{
	CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01_good();
}
