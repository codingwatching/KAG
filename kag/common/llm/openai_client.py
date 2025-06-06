# -*- coding: utf-8 -*-
# Copyright 2023 OpenSPG Authors
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License
# is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.
import logging
import asyncio

from openai import OpenAI, AsyncOpenAI, AzureOpenAI, AsyncAzureOpenAI, NOT_GIVEN

from kag.interface import LLMClient
from typing import Callable, Optional


from kag.interface.solver.reporter_abc import ReporterABC

logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

AzureADTokenProvider = Callable[[], str]


@LLMClient.register("maas")
@LLMClient.register("openai")
@LLMClient.register("vllm")
class OpenAIClient(LLMClient):
    """
    A client class for interacting with the OpenAI API.

    Initializes the client with an API key, base URL, streaming option, temperature parameter, and default model.

    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "dummy",
        stream: bool = False,
        temperature: float = 0.7,
        timeout: float = None,
        max_rate: float = 1000,
        time_period: float = 1,
        think: bool = False,
        **kwargs,
    ):
        """
        Initializes the OpenAIClient instance.

        Args:
            api_key (str): The API key for accessing the OpenAI API.
            base_url (str): The base URL for the OpenAI API.
            model (str): The default model to use for requests.
            stream (bool, optional): Whether to stream the response. Defaults to False.
            temperature (float, optional): The temperature parameter for the model. Defaults to 0.7.
            timeout (float): The timeout duration for the service request. Defaults to None, means no timeout.
        """
        name = kwargs.pop("name", None)
        if not name:
            name = f"{api_key}{base_url}{model}"
        super().__init__(name, max_rate, time_period, **kwargs)
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.stream = stream
        self.temperature = temperature
        self.timeout = timeout
        self.think = think
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.aclient = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.check()
        logger.debug(
            f"Initialize OpenAIClient with rate limit {max_rate} every {time_period}s"
        )
        logger.info(f"OpenAIClient max_tokens={self.max_tokens}")

    def __call__(self, prompt: str = "", image_url: str = None, **kwargs):
        """
        Executes a model request when the object is called and returns the result.

        Parameters:
            prompt (str): The prompt provided to the model.

        Returns:
            str: The response content generated by the model.
        """
        # Call the model with the given prompt and return the response
        reporter: Optional[ReporterABC] = kwargs.get("reporter", None)
        segment_name = kwargs.get("segment_name", None)
        tag_name = kwargs.get("tag_name", None)
        tools = kwargs.get("tools", None)
        messages = kwargs.get("messages", None)
        if messages is None:
            if image_url:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ]
            else:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {"role": "user", "content": prompt},
                ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=self.stream,
            temperature=self.temperature,
            timeout=self.timeout,
            tools=tools,
            max_tokens=self.max_tokens if self.max_tokens > 0 else NOT_GIVEN,
            extra_body={"chat_template_kwargs": {"enable_thinking": self.think}},
        )
        if not self.stream:
            # reasoning_content = getattr(
            #     response.choices[0].message, "reasoning_content", None
            # )
            # content = response.choices[0].message.content
            # if reasoning_content:
            #     rsp = f"{reasoning_content}\n{content}"
            # else:
            #     rsp = content
            rsp = response.choices[0].message.content
            tool_calls = response.choices[0].message.tool_calls
        else:
            rsp = ""
            tool_calls = None  # TODO: Handle tool calls in stream mode

            for chunk in response:
                if not chunk.choices:
                    continue
                delta_content = getattr(chunk.choices[0].delta, "content", None)
                if delta_content is not None:
                    rsp += delta_content
                    if reporter:
                        reporter.add_report_line(
                            segment_name,
                            tag_name,
                            rsp,
                            status="RUNNING",
                        )
        if reporter:
            reporter.add_report_line(
                segment_name,
                tag_name,
                rsp,
                status="FINISH",
            )
        if tools and tool_calls:
            return response.choices[0].message

        return rsp

    async def acall(self, prompt: str = "", image_url: str = None, **kwargs):
        """
        Executes a model request when the object is called and returns the result.

        Parameters:
            prompt (str): The prompt provided to the model.

        Returns:
            str: The response content generated by the model.
        """
        # Call the model with the given prompt and return the response
        reporter: Optional[ReporterABC] = kwargs.get("reporter", None)
        segment_name = kwargs.get("segment_name", None)
        tag_name = kwargs.get("tag_name", None)
        if reporter:
            reporter.add_report_line(
                segment_name,
                tag_name,
                "",
                status="INIT",
            )

        tools = kwargs.get("tools", None)
        messages = kwargs.get("messages", None)
        if messages is None:
            if image_url:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ]

            else:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {"role": "user", "content": prompt},
                ]
        response = await self.aclient.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=self.stream,
            temperature=self.temperature,
            timeout=self.timeout,
            tools=tools,
            max_tokens=self.max_tokens if self.max_tokens > 0 else NOT_GIVEN,
            extra_body={"chat_template_kwargs": {"enable_thinking": self.think}},
        )
        if not self.stream:
            # reasoning_content = getattr(
            #     response.choices[0].message, "reasoning_content", None
            # )
            # if reasoning_content:
            #     rsp = f"{reasoning_content}\n{content}"
            # else:
            rsp = response.choices[0].message.content
            tool_calls = response.choices[0].message.tool_calls
        else:
            rsp = ""
            tool_calls = None
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta_content = getattr(chunk.choices[0].delta, "content", None)
                if delta_content is not None:
                    rsp += delta_content
                if reporter:
                    reporter.add_report_line(
                        segment_name,
                        tag_name,
                        rsp,
                        status="RUNNING",
                    )
        if reporter:
            reporter.add_report_line(
                segment_name,
                tag_name,
                rsp,
                status="FINISH",
            )
        if tools and tool_calls:
            return response.choices[0].message
        return rsp


@LLMClient.register("azure_openai")
class AzureOpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        stream: bool = False,
        api_version: str = "2024-12-01-preview",
        temperature: float = 0.7,
        azure_deployment: str = None,
        timeout: float = None,
        azure_ad_token: str = None,
        azure_ad_token_provider: AzureADTokenProvider = None,
        max_rate: float = 1000,
        time_period: float = 1,
        **kwargs,
    ):
        """
        Initializes the AzureOpenAIClient instance.

        Args:
            api_key (str): The API key for accessing the Azure OpenAI API.
            api_version (str): The API version for the Azure OpenAI API (eg. "2024-12-01-preview, 2024-10-01-preview,2024-05-01-preview").
            base_url (str): The base URL for the Azure OpenAI API.
            azure_deployment (str): The deployment name for the Azure OpenAI model
            model (str): The default model to use for requests.
            stream (bool, optional): Whether to stream the response. Defaults to False.
            temperature (float, optional): The temperature parameter for the model. Defaults to 0.7.
            timeout (float): The timeout duration for the service request. Defaults to None, means no timeout.
            azure_ad_token: Your Azure Active Directory token, https://www.microsoft.com/en-us/security/business/identity-access/microsoft-entra-id
            azure_ad_token_provider: A function that returns an Azure Active Directory token, will be invoked on every request.
            azure_deployment: A model deployment, if given sets the base client URL to include `/deployments/{azure_deployment}`.
                Note: this means you won't be able to use non-deployment endpoints. Not supported with Assistants APIs.
        """
        name = kwargs.pop("name", None)
        if not name:
            name = f"{api_key}{base_url}{model}"
        super().__init__(name, max_rate, time_period, **kwargs)

        self.api_key = api_key
        self.base_url = base_url
        self.azure_deployment = azure_deployment
        self.model = model
        self.stream = stream
        self.temperature = temperature
        self.timeout = timeout
        self.api_version = api_version
        self.azure_ad_token = azure_ad_token
        self.azure_ad_token_provider = azure_ad_token_provider
        self.client = AzureOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            azure_deployment=self.azure_deployment,
            model=self.model,
            api_version=self.api_version,
            azure_ad_token=self.azure_ad_token,
            azure_ad_token_provider=self.azure_ad_token_provider,
        )
        self.aclient = AsyncAzureOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            azure_deployment=self.azure_deployment,
            model=self.model,
            api_version=self.api_version,
            azure_ad_token=self.azure_ad_token,
            azure_ad_token_provider=self.azure_ad_token_provider,
        )

        self.check()
        logger.debug(
            f"Initialize AzureOpenAIClient with rate limit {max_rate} every {time_period}s"
        )

    def __call__(self, prompt: str = "", image_url: str = None, **kwargs):
        """
        Executes a model request when the object is called and returns the result.

        Parameters:
            prompt (str): The prompt provided to the model.

        Returns:
            str: The response content generated by the model.
        """
        # Call the model with the given prompt and return the response
        tools = kwargs.get("tools", None)
        messages = kwargs.get("messages", None)
        if messages is None:
            if image_url:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ]
            else:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {"role": "user", "content": prompt},
                ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=self.stream,
            temperature=self.temperature,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
        )
        rsp = response.choices[0].message.content
        tool_calls = response.choices[0].message.tool_calls
        if tools and tool_calls:
            return response.choices[0].message

        return rsp

    async def acall(self, prompt: str = "", image_url: str = None, **kwargs):
        """
        Executes a model request when the object is called and returns the result.

        Parameters:
            prompt (str): The prompt provided to the model.

        Returns:
            str: The response content generated by the model.
        """
        # Call the model with the given prompt and return the response
        tools = kwargs.get("tools", None)
        messages = kwargs.get("messages", None)
        if messages is None:
            if image_url:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ]

            else:
                messages = [
                    {"role": "system", "content": "you are a helpful assistant"},
                    {"role": "user", "content": prompt},
                ]
        response = await self.aclient.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=self.stream,
            temperature=self.temperature,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
        )
        rsp = response.choices[0].message.content
        tool_calls = response.choices[0].message.tool_calls

        if tools and tool_calls:
            return rsp.choices[0].message
        return rsp


if __name__ == "__main__":
    client = OpenAIClient(
        model="Qwen/Qwen3-0.6B", base_url="http://0.0.0.0:8000/v1", think=False
    )
    msg = asyncio.run(client.acall("你好"))
    print(msg)
