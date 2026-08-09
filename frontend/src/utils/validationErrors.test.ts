import { describe, it, expect } from 'vitest'
import { ApiError } from '../api/client'
import { parseValidationError, fieldErrorInfo } from './validationErrors'

describe('parseValidationError', () => {
  it('returns null for non-ApiError errors', () => {
    expect(parseValidationError(new Error('boom'))).toBeNull()
    expect(parseValidationError('boom')).toBeNull()
  })

  it('returns null for ApiErrors with a non-field detail', () => {
    const e = new ApiError("Schema 'Foo' not found", 404)
    expect(parseValidationError(e)).toBeNull()
  })

  it('maps a date-minimum violation to plain language', () => {
    const e = new ApiError(
      "Field 'recorded_on': 2019-06-01 is before minimum (2020-01-01)",
      422,
    )
    const parsed = parseValidationError(e)
    expect(parsed?.fieldErrors).toEqual({
      recorded_on: 'Must be on or after 1 January 2020.',
    })
    expect(parsed?.message).toBe('Must be on or after 1 January 2020.')
    expect(parsed?.technical).toBe(e.detail)
  })

  it('maps a date-maximum violation to plain language', () => {
    const e = new ApiError(
      "Field 'recorded_on': 2030-01-01 is after maximum (2029-12-31)",
      422,
    )
    expect(parseValidationError(e)?.fieldErrors.recorded_on).toBe(
      'Must be on or before 31 December 2029.',
    )
  })

  it('maps numeric min/max violations', () => {
    expect(
      parseValidationError(
        new ApiError("Field 'age': 5 is below minimum (18)", 422),
      )?.fieldErrors.age,
    ).toBe('Must be at least 18.')
    expect(
      parseValidationError(
        new ApiError("Field 'age': 130 exceeds maximum (120)", 422),
      )?.fieldErrors.age,
    ).toBe('Must be at most 120.')
  })

  it('maps a choices violation', () => {
    const e = new ApiError(
      "Field 'side': 'top' must be one of: left, right, bilateral",
      422,
    )
    expect(parseValidationError(e)?.fieldErrors.side).toBe(
      'Must be one of: left, right, bilateral.',
    )
  })

  it('maps a max_length violation', () => {
    const e = new ApiError(
      "Field 'notes': value length 300 exceeds max_length 255",
      422,
    )
    expect(parseValidationError(e)?.fieldErrors.notes).toBe(
      'Must be 255 characters or fewer (currently 300).',
    )
  })

  it('maps a file type violation', () => {
    const e = new ApiError(
      "Field 'attachment': 'report.docx' type '.docx' not allowed — accepted: .csv,.txt",
      422,
    )
    expect(parseValidationError(e)?.fieldErrors.attachment).toBe(
      "'report.docx' isn't an accepted file type. Allowed: .csv,.txt.",
    )
  })

  it('maps a file size violation', () => {
    const e = new ApiError(
      "Field 'attachment': file size 5242880 bytes exceeds max_size 1048576",
      422,
    )
    expect(parseValidationError(e)?.fieldErrors.attachment).toBe(
      'File is too large (5.0 MB). Maximum is 1.0 MB.',
    )
  })

  it('maps a URL format violation', () => {
    const e = new ApiError(
      "Field 'homepage': 'ftp://x' is not a valid URL (must start with http:// or https://)",
      422,
    )
    expect(parseValidationError(e)?.fieldErrors.homepage).toBe(
      'Must be a full URL starting with http:// or https://.',
    )
  })

  it('maps missing required fields, singular and plural', () => {
    const single = parseValidationError(
      new ApiError('Missing required fields: age', 422),
    )
    expect(single?.fieldErrors).toEqual({ age: 'This field is required.' })
    expect(single?.message).toBe("'age' is required.")

    const plural = parseValidationError(
      new ApiError('Missing required fields: age, side', 422),
    )
    expect(plural?.fieldErrors).toEqual({
      age: 'This field is required.',
      side: 'This field is required.',
    })
    expect(plural?.message).toBe('Fill in the required fields: age, side.')
  })

  it('falls back to the raw detail for an unrecognised field message', () => {
    const e = new ApiError("Field 'x': something unexpected happened", 422)
    expect(parseValidationError(e)?.fieldErrors.x).toBe(
      'something unexpected happened',
    )
  })
})

describe('fieldErrorInfo', () => {
  it('returns nothing for no error', () => {
    expect(fieldErrorInfo(null, ['age'], String)).toEqual({
      fieldErrors: {},
      generalMessage: null,
      technical: null,
    })
  })

  it('attributes a known field error without a general message', () => {
    const e = new ApiError("Field 'age': 5 is below minimum (18)", 422)
    const info = fieldErrorInfo(e, ['age', 'side'], String)
    expect(info.fieldErrors).toEqual({ age: 'Must be at least 18.' })
    expect(info.generalMessage).toBeNull()
    expect(info.technical).toBe(e.detail)
  })

  it('falls back to a general message when the field is unknown', () => {
    const e = new ApiError("Field 'ghost': 5 is below minimum (18)", 422)
    const info = fieldErrorInfo(e, ['age'], String)
    expect(info.generalMessage).toBe('Must be at least 18.')
  })

  it('falls back to errorMessage() for unparseable errors', () => {
    const e = new Error('network down')
    const info = fieldErrorInfo(e, ['age'], (err) => (err as Error).message)
    expect(info).toEqual({
      fieldErrors: {},
      generalMessage: 'network down',
      technical: null,
    })
  })
})
