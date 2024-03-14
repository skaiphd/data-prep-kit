import kfp.compiler as compiler
import kfp.components as comp
import kfp.dsl as dsl
from kfp_support.workflow_support.utils import (
    ONE_HOUR_SEC,
    ONE_WEEK_SEC,
    ComponentUtils,
)
from kubernetes import client as k8s_client


# the name of the job script
EXEC_SCRIPT_NAME: str = "transformer_launcher.py"
RUN_ID = "00"


# components
base_kfp_image = "us.icr.io/cil15-shared-registry/preprocessing-pipelines/kfp-guf:0.0.1-test2"

compute_exec_params_op = comp.func_to_container_op(
    func=ComponentUtils.default_compute_execution_params, base_image=base_kfp_image
)
execute_ray_jobs_op = comp.load_component_from_file("../../../kfp_ray_components/executeRayComponent.yaml")
start_ray_op = comp.load_component_from_file("../../../kfp_ray_components/startRayComponent.yaml")
shutdown_ray_op = comp.load_component_from_file("../../../kfp_ray_components/stopRayComponent.yaml")

# Task name is part of the pipeline name, the ray cluster name and the job name in DMF.
TASK_NAME: str = "noop"

# Pipeline to invoke execution on remote resource


@dsl.pipeline(
    name=TASK_NAME + "-ray-pipeline",
    description="Pipeline for noop",
)
def noop(
    ray_name: str = "noop-kfp-ray",  # name of Ray cluster
    ray_head_options: str = '{"cpu": 1, "memory": 16, "image": "us.icr.io/cil15-shared-registry/preprocessing-pipelines/noop:guftest",\
             "image_pull_secret": "prod-all-icr-io"}',
    ray_worker_options: str = '{"replicas": 1, "max_replicas": 1, "cpu": 4, "memory": 16, "image_pull_secret": "prod-all-icr-io",\
            "image": "us.icr.io/cil15-shared-registry/preprocessing-pipelines/noop:guftest"}',
    server_url: str = "http://kuberay-apiserver-service.kuberay.svc.cluster.local:8888",
    additional_params: str = '{"wait_interval": 2, "wait_cluster_ready_tmout": 400, "wait_cluster_up_tmout": 300, "wait_cluster_nodes_ready_tmout": 100, "wait_job_ready_tmout": 400, "wait_job_ready_retries": 100, "wait_print_tmout": 120, "http_retries": 5, "image_pull_secret": "prod-all-icr-io"}',
    noop_sleep_sec: int = 50,
    lh_config: str = "None",
    max_files: int = -1,
    actor_options: str = "{'num_cpus': 0.8}",
    pipeline_id: str = "pipeline_id",
    job_id: str = "job_id",
    cos_access_secret: str = "cos-access",
    s3_config: str = "{'input_folder': 'cos-optimal-llm-pile/doc_annotation_test/input/noop_small/', 'output_folder': 'cos-optimal-llm-pile/doc_annotation_test/output_noop_guf/'}",
):
    clean_up_task = shutdown_ray_op(ray_name=ray_name, run_id=RUN_ID, server_url=server_url)
    ComponentUtils.add_settings_to_component(clean_up_task, 60)

    with dsl.ExitHandler(clean_up_task):
        # invoke pipeline
        compute_exec_params = compute_exec_params_op(
            worker_options=ray_worker_options,
            actor_options=actor_options,
        )
        ComponentUtils.add_settings_to_component(compute_exec_params, ONE_HOUR_SEC * 2)

        ray_cluster = start_ray_op(
            ray_name=ray_name,
            run_id=RUN_ID,
            ray_head_options=ray_head_options,
            ray_worker_options=ray_worker_options,
            server_url=server_url,
            additional_params=additional_params,
        )
        ComponentUtils.add_settings_to_component(ray_cluster, ONE_HOUR_SEC * 2)

        execute_job = execute_ray_jobs_op(
            ray_name=ray_name,
            run_id=RUN_ID,
            additional_params=additional_params,
            exec_params={
                "s3_config": s3_config,
                "noop_sleep_sec": noop_sleep_sec,
                "lh_config": lh_config,
                "max_files": max_files,
                "num_workers": compute_exec_params.output,
                "worker_options": actor_options,
                "pipeline_id": pipeline_id,
                "job_id": job_id,
            },
            exec_script_name=EXEC_SCRIPT_NAME,
            server_url=server_url,
        )
        ComponentUtils.add_settings_to_component(execute_job, ONE_WEEK_SEC)
        ComponentUtils.set_s3_env_vars_to_component(execute_job, cos_access_secret)

        execute_job.after(ray_cluster)

    # set image pull secrets
    dsl.get_pipeline_conf().set_image_pull_secrets([k8s_client.V1ObjectReference(name="prod-all-icr-io")])
    # Configure the pipeline level to one week (in seconds)
    dsl.get_pipeline_conf().set_timeout(ONE_WEEK_SEC)


if __name__ == "__main__":
    # Compiling the pipeline
    compiler.Compiler().compile(noop, __file__.replace(".py", ".yaml"))
