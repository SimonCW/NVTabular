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
import logging

from nvtabular.graph.node import Node, iter_nodes
from nvtabular.graph.schema import Schema

LOG = logging.getLogger("nvtabular")


class Graph:
    def __init__(self, output_node: Node):
        self.output_node = output_node

        self.input_dtypes = None
        self.output_dtypes = None

        self.input_schema = None
        self.output_schema = None

    def fit_schema(self, root_schema: Schema) -> "Graph":
        schemaless_nodes = {
            node: _get_schemaless_nodes(node.parents_with_dependencies)
            for node in _get_schemaless_nodes([self.output_node])
        }

        while schemaless_nodes:
            # get all the Operators with no outstanding dependencies
            current_phase = [
                node for node, dependencies in schemaless_nodes.items() if not dependencies
            ]
            if not current_phase:
                # this shouldn't happen, but lets not infinite loop just in case
                raise RuntimeError("failed to find dependency-free Operator to compute schema for")

            processed_nodes = []
            for node in current_phase:
                if not node.parents:
                    node.compute_schemas(root_schema)
                else:
                    combined_schema = sum(
                        [parent.output_schema for parent in node.parents if parent.output_schema],
                        Schema(),
                    )
                    # we want to update the input_schema with new values
                    # from combined schema
                    combined_schema = root_schema + combined_schema
                    node.compute_schemas(combined_schema)

                processed_nodes.append(node)

            # Remove all the operators we processed in this phase, and remove
            # from the dependencies of other ops too
            for schemaless_node in current_phase:
                schemaless_nodes.pop(schemaless_node)
            for dependencies in schemaless_nodes.values():
                dependencies.difference_update(current_phase)

        self.input_schema = Schema(
            [
                schema
                for name, schema in root_schema.column_schemas.items()
                if name in self._input_columns()
            ]
        )
        self.output_schema = self.output_node.output_schema

        return self

    def _input_columns(self):
        input_cols = []
        for node in iter_nodes([self.output_node]):
            upstream_output_cols = []

            for upstream_node in node.parents_with_dependencies:
                upstream_output_cols += upstream_node.output_columns.names

            upstream_output_cols = _get_unique(upstream_output_cols)
            input_cols += list(set(node.input_columns.names) - set(upstream_output_cols))

        return _get_unique(input_cols)

    def _zero_output_schemas(self):
        """
        Zero out all schemas in order to rerun fit schema after operators
        have run fit and have stats to add to schema.
        """
        for node in iter_nodes([self.output_node]):
            node.output_schema = None
            node.input_schema = None


def _get_schemaless_nodes(nodes):
    schemaless_nodes = []
    for node in iter_nodes(nodes):
        if node.input_schema is None:
            schemaless_nodes.append(node)

    return set(schemaless_nodes)


def _get_ops_by_type(nodes, op_type):
    return set(node for node in iter_nodes(nodes) if isinstance(node.op, op_type))


def _get_unique(cols):
    # Need to preserve order in unique-column list
    return list({x: x for x in cols}.keys())
