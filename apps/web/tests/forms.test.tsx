import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Form, SecretNotice } from '../src/components/ui';

describe('identity forms', () => {
 it('does not submit an invalid email', async () => {
  const submit = vi.fn();
  render(<Form fields={[{name:'email',label:'Email',type:'email',required:true}]} submit={submit}/>);
  fireEvent.change(screen.getByLabelText(/Email/), {target:{value:'not-an-email'}});
  fireEvent.submit(screen.getByRole('button', {name:'Save'}).closest('form')!);
  await waitFor(()=>expect(screen.getByText('Enter a valid email address')).toBeInTheDocument());
  expect(submit).not.toHaveBeenCalled();
 });
 it('offers an explicit dismissal for one-time values', () => {
  const dismiss=vi.fn();
  render(<SecretNotice value="synthetic-display-value" dismiss={dismiss}/>);
  fireEvent.click(screen.getByRole('button', {name:/hide/}));
  expect(dismiss).toHaveBeenCalledOnce();
 });
});

it('clears password inputs after a successful save', async () => {
 const submit=vi.fn().mockResolvedValue(undefined);
 render(<Form fields={[{name:'credential',label:'Credential',type:'password',required:true}]} submit={submit}/>);
 fireEvent.change(screen.getByLabelText(/Credential/),{target:{value:'synthetic-entry'}});
 fireEvent.submit(screen.getByRole('button',{name:'Save'}).closest('form')!);
 await waitFor(()=>expect(submit).toHaveBeenCalledOnce());
 await waitFor(()=>expect(screen.getByLabelText(/Credential/)).toHaveValue(''));
});
