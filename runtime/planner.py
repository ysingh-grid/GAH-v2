"""
Geometry Agent Runtime: Planning Engine
Wraps fast-rlm to generate valid PrimitivePlan models or direct CadQuery scripts with self-repair capabilities.
"""

import logging

import fast_rlm

from rlm.pull_tools import (
    list_primitives,
    list_skills,
    lookup_primitive,
    read_skill,
)
from rlm.rlm_config import config as default_config
from runtime.schema import PrimitivePlan

logger = logging.getLogger(__name__)


def plan_geometry(
    design_intent: str,
    config: fast_rlm.RLMConfig = None,
    max_attempts: int = 3,
    backend_url: str = "http://127.0.0.1:8001",
    run_prefix: str = "geometry_plan",
) -> PrimitivePlan:
    """
    Executes the planning loop to generate a valid PrimitivePlan using fast-rlm.
    Includes an automated schema verification & self-repair loop.

    Args:
        design_intent: The natural language design query/specification.
        config: Custom RLMConfig (defaults to global gemini config).
        max_attempts: Maximum number of schema repair attempts before failing.
        backend_url: FastAPI server URL accessible by Deno/Pyodide sandbox.
        run_prefix: File prefix for logging fast-rlm transcripts.

    Returns:
        A validated PrimitivePlan object.

    Raises:
        ValueError: If a valid plan cannot be generated within max_attempts.
    """
    active_config = config if config is not None else default_config
    error_msg = None

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Attempt %d/%d: Prompting planner model %s...",
            attempt,
            max_attempts,
            active_config.primary_agent,
        )

        prompt = design_intent
        if error_msg:
            prompt += (
                f"\n\n⚠️ YOUR PREVIOUS PLAN FAILED VALIDATION:\n{error_msg}\n\n"
                f"Please review the primitive parameter types, check the library schema via lookup_primitive, "
                f"and correct all errors."
            )

        try:
            # Run fast-rlm agent
            result = fast_rlm.run(
                prompt,
                config=active_config,
                prefix=f"{run_prefix}_att_{attempt}",
                tools=[list_primitives, lookup_primitive, list_skills, read_skill],
                env_variables={"DTCM_BACKEND_URL": backend_url},
                output_schema=PrimitivePlan,
            )

            raw_results = result.get("results")
            if not raw_results:
                raise ValueError("Planner agent returned empty results.")

            # Validate against Pydantic schema on host side
            plan_data = PrimitivePlan.model_validate(raw_results)
            logger.info("Plan successfully generated and validated on attempt %d!", attempt)
            return plan_data

        except Exception as e:
            error_msg = str(e)
            logger.warning(
                "Attempt %d/%d failed plan validation: %s", attempt, max_attempts, error_msg
            )
            if attempt < max_attempts:
                logger.info(
                    "Waiting 15 seconds to let API rate limits cool down before retrying..."
                )
                import time

                time.sleep(15)

    raise ValueError(
        f"Failed to generate a valid plan after {max_attempts} attempts. Last error: {error_msg}"
    )


def generate_cadquery_code(
    design_intent: str,
    config: fast_rlm.RLMConfig = None,
    max_attempts: int = 3,
    backend_url: str = "http://127.0.0.1:8001",
    run_prefix: str = "cadquery_gen",
) -> str:
    """
    Directly generates CadQuery Python code using fast-rlm and the cadquery_kb.json database.
    Validates code syntax and execution via sandbox, retrying with the traceback on error.

    Args:
        design_intent: The natural language design query/specification.
        config: Custom RLMConfig (defaults to global gemini config).
        max_attempts: Maximum number of code generation attempts before failing.
        backend_url: FastAPI server URL accessible by Deno/Pyodide sandbox.
        run_prefix: File prefix for logging fast-rlm transcripts.

    Returns:
        A valid, executable CadQuery Python script string.

    Raises:
        ValueError: If a valid script cannot be generated within max_attempts.
    """
    from rlm.pull_tools import lookup_cadquery_api, search_cadquery_api
    from tools.execute_cadquery import execute_cadquery

    active_config = config if config is not None else default_config
    error_msg = None

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Attempt %d/%d: Querying model %s for CadQuery code...",
            attempt,
            max_attempts,
            active_config.primary_agent,
        )

        prompt = design_intent
        if error_msg:
            prompt += (
                f"\n\n⚠️ YOUR PREVIOUS CODE FAILED EXECUTION IN THE SANDBOX:\n{error_msg}\n\n"
                f"Please inspect the error trace, search the API using search_cadquery_api, "
                f"verify method signatures with lookup_cadquery_api, and correct all errors."
            )

        try:
            # Run fast-rlm agent to generate the raw python code string
            result = fast_rlm.run(
                prompt,
                config=active_config,
                prefix=f"{run_prefix}_att_{attempt}",
                tools=[search_cadquery_api, lookup_cadquery_api, list_skills, read_skill],
                env_variables={"DTCM_BACKEND_URL": backend_url},
                output_schema=str,  # expect raw string back
            )

            raw_code = result.get("results")
            if not raw_code:
                raise ValueError("Planner agent returned empty code.")

            # Validate execution by running the code in the sandbox
            logger.info("Verifying generated code in sandbox...")
            exec_result = execute_cadquery(raw_code, f"{run_prefix}_verification")
            if not exec_result.get("success"):
                error_info = exec_result.get("error", "Unknown execution failure.")
                raise ValueError(f"Sandbox execution failed: {error_info}")

            logger.info(
                "Code successfully compiled and verified in sandbox on attempt %d!", attempt
            )
            return raw_code

        except Exception as e:
            error_msg = str(e)
            logger.warning("Attempt %d/%d failed validation: %s", attempt, max_attempts, error_msg)
            if attempt < max_attempts:
                logger.info(
                    "Waiting 15 seconds to let API rate limits cool down before retrying..."
                )
                import time

                time.sleep(15)

    raise ValueError(
        f"Failed to generate valid CadQuery code after {max_attempts} attempts. Last error: {error_msg}"
    )
