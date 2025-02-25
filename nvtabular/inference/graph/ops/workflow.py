#
# Copyright (c) 2021, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import pathlib
import warnings

from nvtabular.graph.schema import Schema
from nvtabular.graph.selector import ColumnSelector
from nvtabular.inference.graph.ops.operator import InferenceOperator
from nvtabular.inference.triton.ensemble import (
    _generate_nvtabular_config,
    _remove_columns,
    _triton_datatype_to_dtype,
)


class WorkflowOp(InferenceOperator):
    def __init__(
        self,
        workflow,
        name=None,
        sparse_max=None,
        max_batch_size=None,
        label_columns=None,
        cats=None,
        conts=None,
    ):
        self.workflow = workflow
        self.sparse_max = sparse_max or {}
        self.name = name or self.__class__.__name__.lower()
        self.max_batch_size = max_batch_size
        self.label_columns = label_columns or []
        self.cats = cats or []
        self.conts = conts or []

    def compute_output_schema(self, input_schema: Schema, col_selector: ColumnSelector) -> Schema:
        expected_input = input_schema.apply(col_selector)

        if not expected_input == self.workflow.graph.input_schema:
            raise ValueError(
                "Request schema provided to WorkflowOp doesn't match workflow's input schema.\n"
                f"Request schema columns: {input_schema.column_names}\n"
                f"Workflow input schema columns: {self.workflow.graph.input_schema.column_names}."
            )

        return self.workflow.output_schema

    def export(self, path, consumer_config=None, version=1):
        """Create a directory inside supplied path based on our export name"""
        new_dir_path = pathlib.Path(path) / self.export_name
        new_dir_path.mkdir()

        workflow = _remove_columns(self.workflow, self.label_columns)

        # override the output dtype of the nvtabular model if necessary (fixes mismatches
        # in dtypes between tf inputs and nvt outputs)
        if consumer_config:
            for column in consumer_config.input:
                tf_dtype = _triton_datatype_to_dtype(column.data_type)
                nvt_dtype = workflow.output_dtypes.get(column.name)
                if nvt_dtype and nvt_dtype != tf_dtype:
                    warnings.warn(
                        f"TF model expects {tf_dtype} for column {column.name}, but workflow "
                        f" is producing type {nvt_dtype}. Overriding dtype in NVTabular workflow."
                    )
                    workflow.output_dtypes[column.name] = tf_dtype

        # TODO: Extract this logic to base inference operator?
        export_path = new_dir_path / str(version) / self.export_name
        workflow.save(str(export_path))

        return _generate_nvtabular_config(
            workflow,
            self.export_name,
            new_dir_path,
            backend="nvtabular",
            sparse_max=self.sparse_max,
            max_batch_size=self.max_batch_size,
            cats=self.cats,
            conts=self.conts,
        )

    @property
    def export_name(self):
        return self.name
